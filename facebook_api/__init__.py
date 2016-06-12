import json
import os
import pickle
import random
import urllib.parse
import urllib.request
import requests


def download(url, directory):
    # choose local filename
    base_name = urllib.parse.urlparse(url).path.split('/')[-1]
    file_name = base_name
    while True:
        # add random string to file name to avoid duplicates
        parts = base_name.split('.', 1)
        parts[0] = parts[0][:100]  # cut very long file names
        parts[0] += '_{:08x}'.format(random.randrange(2 ** 32))
        file_name = '.'.join(parts)
        file_name = os.path.join(directory, file_name)
        if not os.path.exists(file_name):
            break
    # download the file
    urllib.request.urlretrieve(url, file_name)
    return file_name


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
            urllib.parse.urlencode(params))
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

    def get_posts_from_group(self, group_id, since=None, until=None):
        fields = ['id',  # post object identifier
                  'type',  # what kind of post this is
                  'from', 'message',  # author and content of the post
                  'link',  # if the author created a link post and deleted the original link
                  'created_time', 'updated_time',  # first & last edit
                  'attachments'  # photos, file uploads, albums, etc
                  ]
        params = {'fields': ','.join(fields)}
        if since is not None:
            params['since'] = since
        if until is not None:
            params['until'] = until
        feed = self._get([group_id, 'feed'], params)
        return (PostRef(res) for res in ResultList(feed))

    def get_posts_from_group_few_fields(self, group_id, since=None, until=None):
        """
        Use for before november 2013 (gets an "unknown error" when asking for all the fields)
        """
        fields = ['id',  # post object identifier
                  'from', 'message',  # author and content of the post
                  'created_time', 'updated_time'  # first & last edit
                  ]
        params = {'fields': ','.join(fields)}
        if since is not None:
            params['since'] = since
        if until is not None:
            params['until'] = until
        feed = self._get([group_id, 'feed'], params)
        return (PostRef(res) for res in ResultList(feed))

    def download_entire_group(self, group_id):
        # new posts
        for post in self.get_posts_from_group(group_id, since='2013-11-01'):
            post.save_into('posts')
            post.fetch_comments(self)
            print(post._updated_time)
        # old posts
        for post in self.get_posts_from_group_few_fields(group_id, until='2013-11-10'):
            if os.path.exists(os.path.join('posts', post._id)):
                continue
            post.save_into('posts')
            post.fetch_comments(self)
            print(post._updated_time)

    def download_group_since(self, group_id, date):
        for post in self.get_posts_from_group(group_id, since=date):
            if os.path.exists(os.path.join('posts', post._id)):
                print('* ', end='', flush=True)
                os.system('rm -r posts/{}'.format(post._id))
            post.save_into('posts')
            post.fetch_comments(self)
            print(post._updated_time)

    def get_post_by_id(self, post_id):
        fields = ['id',  # post object identifier
                  'type',  # what kind of post this is
                  'from', 'message',  # author and content of the post
                  'link',  # if the author created a link post and deleted the original link
                  'created_time', 'updated_time',  # first & last edit
                  'attachments'  # photos, file uploads, albums, etc
                  ]
        params = {'fields': ','.join(fields)}
        return PostRef(self._get([post_id], params))

    @staticmethod
    def parse_attachments(attachments):
        if attachments is not None:
            for item in ResultList(attachments):
                yield item
                if 'subattachments' in item:
                    for subitem in ResultList(item['subattachments']):
                        yield subitem

    def get_comments(self, obj_id, resources_subdir=None):
        fields = ['id', 'from', 'message', 'created_time', 'updated_time',
                  'attachment',  # picture or shared link
                  'comment_count'  # number of sub-comments
                  ]
        comments = self._get([obj_id, 'comments'], {'fields': ','.join(fields)})
        for comment in ResultList(comments):
            if 'attachment' in comment:
                if comment['attachment']['type'] == 'photo':
                    comment['attachment'] = comment['attachment']['media']['image']['src']
                    if resources_subdir:
                        comment['attachment'] = download(comment['attachment'], resources_subdir)
                else:
                    del comment['attachment']
            if comment['comment_count'] > 0:
                comment['comments'] = list(self.get_comments(comment['id'], resources_subdir))
            else:
                comment['comments'] = []
            yield comment


class PostRef(object):
    PICKLE_FILE_NAME = 'post.pickle'

    def __init__(self, fb_dict):

        if isinstance(fb_dict, dict):
            # construct from json
            self._id = fb_dict['id']
            self._from = fb_dict['from']
            self._created_time = fb_dict['created_time']
            self._updated_time = fb_dict['updated_time']

            self._message = fb_dict.get('message', '')
            if fb_dict.get('type') == 'link':
                if 'link' in fb_dict and fb_dict['link'] not in self._message:
                    # user typed a link and then deleted it
                    self._message = fb_dict['link'] + '\n\n' + self._message

            self._pictures = []  # array of urls / file names
            self._attachments = []  # array of (title, url/filename)s

            for attachment in FacebookAPI.parse_attachments(fb_dict.get('attachments')):
                if attachment['type'] == 'photo':
                    self._pictures.append(attachment['media']['image']['src'])
                elif attachment['type'] == 'file_upload':
                    self._attachments.append((attachment['title'], attachment['url']))

            self._comments = None
            self._resources_dir = None

        elif isinstance(fb_dict, str):
            # load from subdirectory
            self._resources_dir = fb_dict
            data = pickle.load(open(os.path.join(self._resources_dir, PostRef.PICKLE_FILE_NAME), 'rb'))
            self._id = data['id']
            self._from = data['from']
            self._created_time = data['created_time']
            self._updated_time = data['updated_time']
            self._message = data['message']
            self._pictures = data['pictures']
            self._attachments = data['attachments']
            self._comments = data['comments']

    @staticmethod
    def load_posts_sorted_by_id(path):
        post_dirs = os.listdir(path)
        post_dirs.sort(key=lambda x: int(x.split('_')[1]))
        return [PostRef(os.path.join(path, directory)) for directory in post_dirs]

    def is_empty(self):
        return self._message.strip() == ''

    def _pickle(self):
        data = {'id': self._id,
                'from': self._from,
                'created_time': self._created_time,
                'updated_time': self._updated_time,
                'message': self._message,
                'pictures': self._pictures,
                'attachments': self._attachments,
                'comments': self._comments}
        pickle.dump(data, open(os.path.join(self._resources_dir, PostRef.PICKLE_FILE_NAME), 'wb'))

    def save_into(self, resources_subdir):
        self._resources_dir = os.path.join(resources_subdir, self._id)
        os.mkdir(self._resources_dir)
        self._pictures = [download(url, self._resources_dir) for url in self._pictures]
        self._attachments = [(title, download(url, self._resources_dir)) for (title, url) in self._attachments]
        self._pickle()

    def fetch_comments(self, api):
        self._comments = list(api.get_comments(self._id, self._resources_dir))
        if self._resources_dir:
            self._pickle()

    def get_all_attachments(self):
        def append_attachments(lst, comments):
            for comment in comments:
                if 'attachment' in comment:
                    lst.append(comment['attachment'])
                append_attachments(lst, comment['comments'])
        res = []
        res += self._pictures
        res += [location for name, location in self._attachments]
        append_attachments(res, self._comments or [])
        return res

    def modify_attachments(self, func):
        def modify_comments(comments):
            for comment in comments:
                if 'attachment' in comment:
                    comment['attachment'] = func(comment['attachment'])
                modify_comments(comment['comments'])
        self._pictures = [func(x) for x in self._pictures]
        self._attachments = [(x, func(y)) for (x, y) in self._attachments]
        modify_comments(self._comments or [])


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
