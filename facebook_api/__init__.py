import json
import random
from urllib.parse import urlencode, urlparse
from urllib.request import urlretrieve

import requests


class GraphProtocol(object):
    GRAPH_API_URL = 'https://graph.facebook.com'

    def __init__(self):
        assert False

    @staticmethod
    def get(version, path, params):
        """
        Create a URL and GET the result from the Graph API
        """
        assert 'access_token' in params
        url = '{}/{}/{}?{}'.format(
            GraphProtocol.GRAPH_API_URL,
            version,
            '/'.join(path),
            urlencode(params))
        return GraphProtocol.get0(url)

    @staticmethod
    def get0(url):
        """
        Send a GET request and convert the result to JSON
        """
        r = requests.get(url)

        if r.status_code == 200:
            try:
                return json.loads(r.text)
            except json.JSONDecodeError:
                raise Exception('Non-JSON response from facebook on URL {}'.format(url))
        else:
            try:
                message = json.loads(r.text)['error']['message']
            except (json.JSONDecodeError, KeyError, TypeError) as _:
                message = r.text
            raise Exception('Error {}: {}'.format(r.status_code, message))


# noinspection SpellCheckingInspection
def download(url):
    """
    Download the file in the URL specified, and return local filename
    """
    # munge filename for uniqueness
    file_name = urlparse(url).path.split('/')[-1]
    file_name_parts = file_name.split('.')
    file_name_parts[0] += '_{:08x}'.format(random.randrange(2 ** 32))
    file_name = '.'.join(file_name_parts)
    # download
    urlretrieve(url, file_name)
    return file_name


class FacebookAPI(object):
    ALLOWED_VERSIONS = {'v2.6'}

    def __init__(self, access_token, version='v2.6', debug=False):
        assert version in FacebookAPI.ALLOWED_VERSIONS
        self._access_token = access_token
        self._version = version
        self._debug = debug

    def _get(self, hierarchy, params=None):
        if params is None:
            params = {}
        else:
            params = params.copy()
        params['access_token'] = self._access_token
        if self._debug:
            print('/'.join(hierarchy))
        return GraphProtocol.get(self._version, hierarchy, params)

    def search(self, query, typ):
        """
        Performs a Facebook search, returning an iterator of results.
        :param query: thing to search for
        :param typ: only search among this post type
        :return: a ResultList with id,name keys
        """
        return ResultList(self._get(['search'], {'q': query, 'type': typ, 'fields': 'id,name'}))

    def get_posts_from_group(self, obj_id, dl_resources=False):
        # TODO: give an option to limit by time
        fields = ['id',  # post object identifier
                  'type',  # what kind of post this is
                  'from', 'message',  # author and content of the post
                  'link',  # if the author created a link post and deleted the original link
                  'created_time', 'updated_time',  # first & last edit
                  'attachments'  # photos, file uploads, albums, etc
                  ]
        feed = self._get([obj_id, 'feed'], {'fields': ','.join(fields)})
        for post in ResultList(feed):
            yield self.handle_post(post, dl_resources)

    @staticmethod
    def _parse_attachments(attachments):
        if attachments is not None:
            for item in ResultList(attachments):
                yield item
                if 'subattachments' in item:
                    for subitem in ResultList(item['subattachments']):
                        yield subitem

    def handle_post(self, post, dl_resources):
        if 'message' not in post:
            post['message'] = ''
        if 'link' in post:
            if post['type'] == 'link' and post['link'] not in post['message']:
                post['message'] = '{}\n\n{}'.format(post['link'], post['message'])
            del post['link']
        del post['type']

        attachment_list = list(FacebookAPI._parse_attachments(post.get('attachments')))
        post['pictures'] = []
        post['attachments'] = []
        for attachment in attachment_list:
            if attachment['type'] == 'photo':
                post['pictures'].append(attachment['media']['image']['src'])
            elif attachment['type'] == 'file_upload':
                post['attachments'].append((attachment['title'], attachment['url']))

        if dl_resources:
            post['pictures'] = [download(url) for url in post['pictures']]
            post['attachments'] = [(title, download(url)) for (title, url) in post['attachments']]

        post['comments'] = list(self.get_comments(post['id'], dl_resources))

        return post

    def get_comments(self, obj_id, dl_resources=False):
        fields = ['id', 'from', 'message', 'created_time', 'updated_time',
                  'attachment',  # picture or shared link
                  'comment_count'  # number of sub-comments
                  ]
        comments = self._get([obj_id, 'comments'], {'fields': ','.join(fields)})
        for comment in ResultList(comments):
            if 'attachment' in comment:
                if comment['attachment']['type'] == 'photo':
                    comment['attachment'] = comment['attachment']['media']['image']['src']
                    if dl_resources:
                        comment['attachment'] = download(comment['attachment'])
                else:
                    del comment['attachment']
            if comment['comment_count'] > 0:
                comment['comments'] = list(self.get_comments(comment['id'], dl_resources))
            else:
                comment['comments'] = []
            yield comment


class ResultList(object):
    def __init__(self, first_response):
        """
        Incremental generator for results returned from a query
        :param first_response: starting point for the list
        """
        self._save(first_response)

    def _save(self, response):
        try:
            self._data = response['data']
            self._i = 0
            self._next_url = response.get('paging', {}).get('next')
        except (KeyError, TypeError) as _:
            raise Exception('Invalid response from facebook')

    def __iter__(self):
        return self

    def __next__(self):
        while self._i == len(self._data):
            if self._next_url is None:
                raise StopIteration
            self._save(GraphProtocol.get0(self._next_url))

        x = self._data[self._i]
        self._i += 1
        return x
