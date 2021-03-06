# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at http://mozilla.org/MPL/2.0/.

import time
import logging
import pickle
from bisect import bisect
from collections import defaultdict

import markus
import ujson as json

from django_redis import get_redis_connection

from django.conf import settings
from django.http import HttpResponse
from django.core.cache import cache, caches
from django.views.decorators.csrf import csrf_exempt
from django.template.defaultfilters import filesizeformat as dj_filesizeformat
from django.core.exceptions import ImproperlyConfigured

from tecken.base.symboldownloader import (
    SymbolDownloader,
    SymbolNotFound,
    SymbolDownloadError,
)
from tecken.base.decorators import set_request_debug


logger = logging.getLogger('tecken')
metrics = markus.get_metrics('tecken')
store = caches['store']

downloader = SymbolDownloader(settings.SYMBOL_URLS)


def filesizeformat(bytes):
    """the function django.template.defaultfilters.filesizeformat is
    nifty but it's meant for displaying in templates so it uses a
    whitespace-looking character instead of a space so it doesn't
    break in display. We don't need that here in this context."""
    return dj_filesizeformat(bytes).replace('\xa0', ' ')


class SymbolFileEmpty(Exception):
    """Happens when we 200 OK download a file that exists but is
    entirely empty."""


class LogCacheHitsMixin:
    """Mixing for storing information about cache hits and misses.
    """

    def log_symbol_cache_miss(self):
        metrics.incr('cache_miss', 1)

    def log_symbol_cache_hit(self):
        metrics.incr('cache_hit', 1)


class JsonResponse(HttpResponse):
    """
    An "overwrite" of django.http.JsonResponse that uses "our"
    imported json instead which can be ujson.
    The only difference is that it never tries to be smart about
    sending in an encoder to take care of tricky types like
    Decimals and datetime objects.
    """

    def __init__(self, data, safe=True,
                 json_dumps_params=None, **kwargs):
        if safe and not isinstance(data, dict):
            raise TypeError(
                'In order to allow non-dict objects to be serialized set the '
                'safe parameter to False.'
            )
        if json_dumps_params is None:
            json_dumps_params = {}
        kwargs.setdefault('content_type', 'application/json')
        data = json.dumps(data, **json_dumps_params)
        super().__init__(content=data, **kwargs)


class SymbolicateJSON(LogCacheHitsMixin):
    def __init__(self, stacks, memory_map, debug=False):
        self.stacks = stacks
        self.memory_map = memory_map
        self.debug = debug
        # per request global map of all symbol maps
        self.all_symbol_maps = {}
        # the result we will populate
        self.result = {
            'symbolicatedStacks': [],
            'knownModules': [False] * len(memory_map),
        }
        self._run()

    def add_to_symbols_maps(self, key, map_):
        # When inserting to the function global all_symbol_maps
        # store it as a tuple with an additional value (for
        # the sake of optimization) of the sorted list of ALL
        # offsets as int16s ascending order.
        self.all_symbol_maps[key] = (
            map_,
            sorted(map_)
        )

    def _run(self):
        # Record the total time it took to symbolicate
        t0 = time.time()

        cache_lookup_times = []
        download_times = []
        download_sizes = []
        modules_lookups = {}

        # First look up all symbols that we're going to need so that
        # when it's time to really loop over `self.stacks` the
        # 'self.all_symbol_maps' should be fully populated as well as it
        # can be.
        needs_to_be_downloaded = set()
        for stack in self.stacks:
            for module_index, module_offset in stack:
                if module_index < 0:
                    continue
                filename, debug_id = self.memory_map[module_index]
                symbol_key = (filename, debug_id)
                # Keep a dict of the symbol keys and each's module index
                modules_lookups[symbol_key] = module_index

        # get_symbol_maps() takes a list of symbol keys, does a Redis
        # GETMANY over all of them, then returns a dict containing
        # metrics about that lookup and a dict called 'symbols'
        # which has the individual information for each symbol.
        informations = self.get_symbol_maps(modules_lookups)

        # Hit or miss, there was a cache lookup
        if self.debug:
            cache_lookup_times.append(
                informations['cache_lookup_time']
            )

        # Now loop over every symbol looked up from get_symbol_maps()
        # Expect that, for every symbol, there is something. Even
        # though it might be empty. If it's empty (i.e. no 'symbol_map' key)
        # it means we looked in the cache but it not in the cache.
        for symbol_key, information in informations['symbols'].items():
            module_index = modules_lookups[symbol_key]
            if 'symbol_map' in information:
                # We were able to look it up from cache.
                symbol_map = information['symbol_map']
                # But even though it was in cache it might have just
                # been cached temporarily because it has previously
                # failed.
                found = information['found']

                # If it was successfully fetched from cache,
                # these metrics will be available.
                self.result['knownModules'][module_index] = found
                self.add_to_symbols_maps(symbol_key, symbol_map)
            else:
                # These are the symbols that we're going to have to
                # download from the Internet.
                needs_to_be_downloaded.add((
                    symbol_key,
                    module_index
                ))

        # Now let's go ahead and download the symbols that need to be
        # fetched over the network.
        if needs_to_be_downloaded:
            # The self.load_symbols() method can cope
            # with 'needs_to_be_downloaded' being an empty list, as
            # there is simply nothing to do.
            # But we avoid the call since it has a timer on it. Otherwise
            # we get many timer timings that are unrealistically small
            # which makes it hard to see how long it takes.
            downloaded = self.load_symbols(needs_to_be_downloaded)
            for symbol_key, information, module_index in downloaded:
                symbol_map = information['symbol_map']
                self.add_to_symbols_maps(symbol_key, symbol_map)
                if self.debug:
                    if 'download_time' in information:
                        download_times.append(information['download_time'])
                    if 'download_size' in information:
                        download_sizes.append(information['download_size'])
                found = information['found']
                self.result['knownModules'][module_index] = found

        # Initialize counters of how many stacks we do symbolication on.
        # Some stacks are malformed so we can't symbolicate them
        # so we keep a seperation between "total" and "real". Always
        # expect real_stacks <= total_stacks.
        total_stacks = 0
        real_stacks = 0

        # This counter is for the sake of the debug output. So you can
        # get an appreciation how much was needed from each module (aka
        # symbol).
        stacks_per_module = defaultdict(int)

        # Now that all needed symbols are looked up, we should be
        # ready to symbolicate for reals.
        for stack in self.stacks:
            response_stack = []
            for module_index, module_offset in stack:
                total_stacks += 1
                if module_index < 0:
                    try:
                        response_stack.append(hex(module_offset))
                    except TypeError:
                        metrics.incr('typerror', 1)
                        # Happens if 'module_offset' is not an int16
                        # and thus can't be represented in hex.
                        response_stack.append(str(module_offset))
                    continue

                real_stacks += 1

                symbol_filename, debug_id = self.memory_map[module_index]

                symbol_key = (symbol_filename, debug_id)

                # This 'stacks_per_module' will only be used in the debug
                # output. So give it a string key instead of a tuple.
                stacks_per_module['{}/{}'.format(*symbol_key)] += 1

                symbol_map, symbol_offset_list = self.all_symbol_maps.get(
                    symbol_key,
                    ({}, [])
                )
                signature = symbol_map.get(module_offset)
                # If it wasn't an immediate match in the map, look up
                # the nearest signature rounded down.
                if signature is None and symbol_map:
                    signature = symbol_map[
                        symbol_offset_list[
                            bisect(symbol_offset_list, module_offset) - 1
                        ]
                    ]

                response_stack.append(
                    '{} (in {})'.format(
                        signature or hex(module_offset),
                        symbol_filename
                    )
                )
            self.result['symbolicatedStacks'].append(response_stack)

        t1 = time.time()

        logger.info(
            'The whole symbolication of {} ({} actual) '
            'stacks took {:.4f} seconds'.format(
                total_stacks,
                real_stacks,
                t1 - t0,
            )
        )

        if self.debug:
            self.result['debug'] = {
                'time': t1 - t0,
                'stacks': {
                    'count': total_stacks,
                    'real': real_stacks,
                },
                'modules': {
                    'count': len(modules_lookups),
                    'stacks_per_module': stacks_per_module,
                },
                'cache_lookups': {
                    'count': len(cache_lookup_times),
                    'time': float(sum(cache_lookup_times)),
                },
                'downloads': {
                    'count': len(download_times),
                    'time': float(sum(download_times)),
                    'size': float(sum(download_sizes)),
                }
            }

    @staticmethod
    def _make_cache_key(symbol_key):
        return 'symbol:{}/{}'.format(*symbol_key)

    @metrics.timer_decorator('cache_lookup_symbols')
    def get_symbol_maps(self, symbol_keys):
        cache_keys = {self._make_cache_key(x): x for x in symbol_keys}
        # output of 'store.get_many' is an OrderedDict
        t0 = time.time()
        many = store.get_many(cache_keys.keys())
        t1 = time.time()
        informations = {
            'symbols': {},
        }

        for cache_key in cache_keys:
            symbol_key = cache_keys[cache_key]
            information = {}

            symbol_map = many.get(cache_key)
            if symbol_map is None:  # not existant in cache
                # Need to download this from the Internet.
                self.log_symbol_cache_miss()
                # If the symbols weren't in the cache, this will be dealt
                # with later by this method's caller.
            else:
                assert isinstance(symbol_map, dict)
                if not symbol_map:
                    # It was cached but empty. That means it was logged that
                    # it was previously attempted but failed.
                    # The reason it's cached is to avoid it being looked up
                    # again and again when it's just going to continue to fail.
                    information['symbol_map'] = {}
                    information['found'] = False
                else:
                    self.log_symbol_cache_hit()
                    # If it was in cache, that means it was originally found.
                    information['symbol_map'] = symbol_map
                    information['found'] = True
            informations['symbols'][symbol_key] = information

        if self.debug:
            informations['cache_lookup_time'] = t1 - t0
        return informations

    def load_symbols(self, requirements):
        """return a list that contains items of 3-tuples of
        (symbol_key, information, module_index)
        """
        # XXX This could be done concurrently
        for symbol_key, module_index in requirements:
            cache_key = self._make_cache_key(symbol_key)
            information = {}
            try:
                information.update(self.load_symbol(*symbol_key))
                if not information['download_size']:
                    raise SymbolFileEmpty()
                assert isinstance(information['symbol_map'], dict)
                store.set(
                    cache_key,
                    information['symbol_map'],
                    # When doing local dev, only store it for 100 min
                    # But in prod set it to indefinite.
                    timeout=settings.DEBUG and 60 * 100 or None
                )
                # The current configuration of how django_redis works is
                # that it uses the default implementation, which is to
                # marshal the objects with pickle as a binary string.
                # More testing is needed to see if this is worth doing
                # since the benefits of using JSON is that the Redis LRU
                # can be opened outside of Python and inspected or mutated.
                # Also, unpickling is inheritly insecure if you can't trust
                # the source. We can, but there's a tiny extra vector if
                # someone hacks our Redis database to inject dangerous
                # binary strings into it.
                symbol_map_size = len(pickle.dumps(information['symbol_map']))
                logger.info(
                    'Storing {!r} ({}) in LRU cache (Took {:.2f}s)'.format(
                        cache_key,
                        filesizeformat(symbol_map_size),
                        information['download_time'],
                    )
                )
                metrics.gauge('storing_symbol', symbol_map_size)
                information['found'] = True

                # We don't need to know the store cache's memory usage
                # but it's a useful number in understanding how the LRU
                # is behaving. Take this opportunity to send a gauge of
                # the amount of memory the store is using
                redis_store_connection = get_redis_connection('store')
                info = redis_store_connection.info()
                metrics.gauge('store_memory', info['used_memory'])
                metrics.gauge('store_keys', redis_store_connection.dbsize())

            except (SymbolNotFound, SymbolFileEmpty, SymbolDownloadError):
                # If it can't be downloaded, cache it as an empty result
                # so we don't need to do this every time we're asked to
                # look up this symbol.
                store.set(
                    cache_key,
                    {},
                    settings.DEBUG and 60 or 60 * 60,
                )
                # If nothing could be downloaded, keep it anyway but
                # to avoid having to check if 'symbol_map' is None, just
                # turn it into a dict.
                information['symbol_map'] = {}  # override
                information['found'] = False
            yield (symbol_key, information, module_index)

    @metrics.timer_decorator('load_symbol')
    def load_symbol(self, filename, debug_id):
        t0 = time.time()
        stream = self.get_download_symbol_stream(filename, debug_id)

        # Need to parse it by line and make a dict of of offset->function
        public_symbols = {}
        func_symbols = {}
        line_number = 0
        total_size = 0
        t0 = time.time()
        url = next(stream)
        for line in stream:
            total_size += len(line)
            line_number += 1
            if line.startswith('PUBLIC '):
                fields = line.strip().split(None, 3)
                if len(fields) < 4:
                    logger.warning(
                        'PUBLIC line {} in {} has too few fields'.format(
                            line_number,
                            url,
                        )
                    )
                    continue
                address = int(fields[1], 16)
                symbol = fields[3]
                public_symbols[address] = symbol
            elif line.startswith('FUNC '):
                fields = line.strip().split(None, 4)
                if len(fields) < 4:
                    logger.warning(
                        'FUNC line {} in {} has too few fields'.format(
                            line_number,
                            url,
                        )
                    )
                    continue
                address = int(fields[1], 16)
                symbol = fields[4]
                func_symbols[address] = symbol

        # Prioritize PUBLIC symbols over FUNC symbols # XXX why?
        func_symbols.update(public_symbols)
        t1 = time.time()
        if not total_size:
            logger.warning('Downloaded content empty ({!r}, {!r})'.format(
                filename,
                debug_id,
            ))
        information = {}
        information['symbol_map'] = func_symbols
        information['download_time'] = t1 - t0
        information['download_size'] = total_size
        return information

    def get_download_symbol_stream(self, lib_filename, debug_id):
        """
        Return a requests.response stream or raise SymbolNotFound
        if the symbol can't be found at all.
        """
        if lib_filename.endswith('.pdb'):
            symbol_filename = lib_filename[:-4] + '.sym'
        else:
            symbol_filename = lib_filename + '.sym'

        stream = downloader.get_symbol_stream(
            lib_filename,
            debug_id,
            symbol_filename
        )
        return stream


@csrf_exempt
@set_request_debug
@metrics.timer_decorator('symbolicate_json')
def symbolicate_json(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Must use HTTP POST'}, status=405)
    try:
        json_body = json.loads(request.body.decode('utf-8'))
        if not isinstance(json_body, dict):
            return JsonResponse({'error': 'Not a dict'}, status=400)
    except ValueError as exception:
        return JsonResponse({'error': 'Invalid JSON passed in'}, status=400)

    try:
        stacks = json_body['stacks']
        memory_map = json_body['memoryMap']
        if json_body.get('version') != 4:
            return JsonResponse({'error': 'Expect version==4'}, status=400)
    except KeyError as exception:
        return JsonResponse({'error': 'Missing key JSON "{}"'.format(
            exception
        )}, status=400)

    symbolicator = SymbolicateJSON(
        stacks,
        memory_map,
        debug=request._request_debug,
    )
    return JsonResponse(symbolicator.result)


def metrics_insight(request):
    markus_backend_classes = [x['class'] for x in settings.MARKUS_BACKENDS]
    if 'tecken.markus_extra.CacheMetrics' not in markus_backend_classes:  # noqa
        raise ImproperlyConfigured(
            'It only makes sense to use this view when you have configured '
            "to use the 'tecken.markus_extra.CacheMetrics' backend."
        )

    count_keys = len(list(store.iter_keys('symbol:*')))
    sum_hits = cache.get('tecken.cache_hit', 0)
    sum_misses = cache.get('tecken.cache_miss', 0)

    sum_stored = cache.get('tecken.storing_symbol')
    sum_retrieved = cache.get('tecken.retrieving_symbol')

    context = {}
    context['keys'] = count_keys
    context['hits'] = sum_hits
    context['misses'] = sum_misses
    if sum_hits or sum_misses:
        context['ratio_of_hits'] = sum_hits / (sum_hits + sum_misses)
        context['percent_of_hits'] = 100 * context['ratio_of_hits']

    context['retrieved'] = sum_retrieved,
    context['stored'] = sum_stored

    redis_store_connection = get_redis_connection('store')
    info = redis_store_connection.info()

    context['maxmemory'] = {
        'bytes': info['maxmemory'],
        'human': info['maxmemory_human'],
    }
    context['used_memory'] = {
        'bytes': info['used_memory'],
        'human': info['used_memory_human'],
        'ratio': info['used_memory'] / info['maxmemory'],
        'percent': 100 * info['used_memory'] / info['maxmemory'],
    }
    return JsonResponse(context)
