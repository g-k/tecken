# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at http://mozilla.org/MPL/2.0/.

import csv
import datetime
import logging

import markus

from django import http
from django.conf import settings
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.core.cache import cache

from tecken.base.symboldownloader import SymbolDownloader
from tecken.base.decorators import set_request_debug

logger = logging.getLogger('tecken')
metrics = markus.get_metrics('tecken')

downloader = SymbolDownloader(settings.SYMBOL_URLS)


def _ignore_symbol(symbol, debugid, filename):
    # The MS debugger will always try to look up these files. We
    # never have them in our symbol stores. So it can be safely ignored.
    if filename == 'file.ptr':
        return True
    if debugid == '000000000000000000000000000000000':
        return True

    # The default is to NOT ignore it


@metrics.timer_decorator('download_symbol')
@set_request_debug
@require_http_methods(['GET', 'HEAD'])
def download_symbol(request, symbol, debugid, filename):
    # First there's an opportunity to do some basic pattern matching on
    # the symbol, debugid, and filename parameters to determine
    # if we can, with confidence, simply ignore it.
    # Not only can we avoid doing a SymbolDownloader call, we also
    # don't have to bother logging that it could not be found.
    if _ignore_symbol(symbol, debugid, filename):
        logger.debug('Ignoring symbol {}/{}/{}'.format(
            symbol,
            debugid,
            filename,
        ))
        response = http.HttpResponseNotFound('Symbol Not Found (and ignored)')
        if request._request_debug:
            response['Debug-Time'] = 0
        return response

    if request.method == 'HEAD':
        if downloader.has_symbol(symbol, debugid, filename):
            response = http.HttpResponse()
            if request._request_debug:
                response['Debug-Time'] = downloader.time_took
            return response
    else:
        url = downloader.get_symbol_url(symbol, debugid, filename)
        if url:
            response = http.HttpResponseRedirect(url)
            if request._request_debug:
                response['Debug-Time'] = downloader.time_took
            return response

    if request.method == 'GET':
        # Only bother logging it if the client used GET.
        # Otherwise it won't be possible to pick up the extra
        # query string parameters.
        log_symbol_get_404(
            symbol,
            debugid,
            filename,
            code_file=request.GET.get('code_file'),
            code_id=request.GET.get('code_id'),
        )

    response = http.HttpResponseNotFound('Symbol Not Found')
    if request._request_debug:
        response['Debug-Time'] = downloader.time_took
    return response


def log_symbol_get_404(
    symbol,
    debugid,
    filename,
    code_file='',
    code_id='',
):
    """Store the fact that a symbol could not be found.

    The purpose of this is be able to query "What symbol fetches have
    recently been attempted and failed?" With that knowledge, we can
    deduce which symbols are commonly needed in symbolication but failed
    to be available. Then you can try to go and get hold of them and
    thus have less symbol 404s in the future.

    Because this is expected to be called A LOT (in particular from
    Socorro's Processor) we have to do this rapidly in a database
    that is suitable for many fast writes.
    See https://bugzilla.mozilla.org/show_bug.cgi?id=1361854#c5
    for the backstory about expected traffic.

    The URL used when requesting the file will only ever be
    'symbol', 'debugid' and 'filename', but some services, like Socorro's
    stackwalker is actually aware of other parameters that are
    relevant only to this URL. Hence 'code_file' and 'code_id' which
    are both optional.
    """
    # In case they are None or something else falsy but not an empty string
    code_file = code_file and code_file.strip() or ''
    code_id = code_id and code_id.strip() or ''

    key = 'missingsymbols:{}:'.format(timezone.now().strftime('%Y-%m-%d'))
    key += '|'.join((
        symbol,
        debugid,
        filename,
        code_file,
        code_id,
    ))
    try:
        cache.incr(key, 1)
    except ValueError:
        # Can't increment if it's never been stored.
        # The first purpose of storing missing symbols is to be able to
        # export a CSV file that lists all missing symbols YESTERDAY.
        # That report needs to contain everything from midnight yesterday
        # until midnight today.
        # So the CSV file is exported at 11PM on a Sunday it needs to
        # include ALL missing symbols from 0AM to 0PM on the Saturday.
        # That's why the expiration time here is the last TWO DAYS.
        cache.set(key, 1, 60 * 60 * 24 * 2)


def missing_symbols_csv(request):
    """return a CSV payload that has yesterdays missing symbols.

    We have a record of every 'symbol', 'debugid', 'filename', 'code_file'
    and 'code_id'. In the CSV export we only want 'symbol', 'debugid',
    'code_file' and 'code_id'.

    There's an opportunity of optimization here.
    This payload is pretty large and requires a lot of memory to generate
    and respond. We could instead use an S3 bucket to store this and
    let S3 handle the download repeatedly.

    Note that this view is expected to be quite resource intensive.
    In Socorro we used to upload a .csv file to S3 on a daily basis.
    This file is what's downloaded and parsed to figure what needs to be
    improved in the symbol store ultimately. We could do some serious
    caching of this view by letting it generate *to* S3 if it hasn't
    already been generated and uploaded to S3.
    """

    date = timezone.now()
    if not request.GET.get('today'):
        # By default we want to look at keys inserted yesterday, but
        # it's useful (for debugging for example) to be able to see what
        # keys have been inserted today.
        date -= datetime.timedelta(days=1)

    response = http.HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        'attachment; filename="missing-symbols-{}.csv"'.format(
            date.strftime('%Y-%m-%d')
        )
    )
    writer = csv.writer(response)
    writer.writerow([
        'debug_file',
        'debug_id',
        'code_file',
        'code_id',
    ])

    key_prefix = 'missingsymbols:{}:'.format(date.strftime('%Y-%m-%d'))
    for key in cache.iter_keys(key_prefix + '*'):
        data = key.replace(key_prefix, '').split('|')
        symbol, debugid, filename, code_file, code_id = data
        writer.writerow([
            symbol,
            debugid,
            code_file,
            code_id,
        ])

    return response
