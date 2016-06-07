import html
import mimetypes
import unicodedata
import time
import datetime
import pytz
import wordpress_xmlrpc
from wordpress_xmlrpc import xmlrpc_client
from wordpress_xmlrpc.methods import posts, comments, media

DEFAULT_TEXT_DIRECTION = 'rtl'
GROUP_TIMEZONE = pytz.timezone('Asia/Jerusalem')


def div_with_direction(content, direction):
    if direction == 'ltr':
        style = 'direction:ltr;text-align:left;'
    elif direction == 'rtl':
        style = 'direction:rtl;text-align:right;'
    else:
        style = ''
    return '<div style="{}">{}</div>'.format(style, html.escape(content))


def format_message(text):
    """
    Convert facebook-style text to wordpress-style text
    """

    lines = text.split('\n')
    direction = DEFAULT_TEXT_DIRECTION
    divs = []
    for line in lines:
        if len(line.strip()) == 0:
            divs.append('<br />')
        else:
            line_bidi = unicodedata.bidirectional(line.strip()[0])
            if line_bidi == 'L':
                direction = 'ltr'
            elif line_bidi == 'R':
                direction = 'rtl'
            divs.append(div_with_direction(line, direction))
    return '\n'.join(divs)


def facebook_timestamp_to_datetime(timestamp):
    epoch_time = time.mktime(time.strptime(timestamp, '%Y-%m-%dT%H:%M:%S%z'))
    return datetime.datetime.fromtimestamp(epoch_time, GROUP_TIMEZONE)


def extract_title(message):
    words = message.split()
    if words[0].startswith('http://') or words[0].startswith('https://'):
        words = words[1:]
    title = words[0]
    for word in words[1:]:
        new_title = title + ' ' + word
        if len(new_title) > 50:
            title += '...'
            break
        title = new_title
    return title


class WordPressAdapter(object):

    def __init__(self, blog_url, username, password, debug=False):
        if blog_url.endswith('/'):
            rpc_url = '{}xmlrpc.php'.format(blog_url)
        else:
            rpc_url = '{}/xmlrpc.php'.format(blog_url)
        self._client = wordpress_xmlrpc.Client(rpc_url, username, password)
        self._debug = debug

    def upload(self, file_name):
        data = {'name': file_name,
                'type': mimetypes.guess_type(file_name)[0],
                'bits': xmlrpc_client.Binary(open(file_name, 'rb').read())}
        result = self._client.call(media.UploadFile(data))
        return result['url']

    def post_from_fb(self, fb_dict, ul_resources=False):
        post = wordpress_xmlrpc.WordPressPost()
        post.title = extract_title(fb_dict['message'])
        post.content = format_message(fb_dict['message'])
        if fb_dict['pictures']:
            if ul_resources:
                fb_dict['pictures'] = [self.upload(f) for f in fb_dict['pictures']]
            images = ''.join('<img src="{}" />\n'.format(url) for url in fb_dict['pictures'])
            post.content = images + '<br />\n' + post.content
        if fb_dict['attachments']:
            if ul_resources:
                fb_dict['attachments'] = [(name, self.upload(f)) for name, f in fb_dict['attachments']]
            attachments = ''.join('<div><a href="{}">{}</a></div>\n'.format(url, name)
                                  for name, url in fb_dict['attachments'])
            post.content += '<br />\n<div>קבצים מצורפים:</div>\n' + attachments
        post.date = facebook_timestamp_to_datetime(fb_dict['created_time'])
        if fb_dict['updated_time'] != fb_dict['created_time']:
            post.date_modified = facebook_timestamp_to_datetime(fb_dict['updated_time'])
        post.terms_names = {'post_tag': [fb_dict['from']['name']]}
        post.post_status = 'publish'
        post.comment_status = 'open'
        if self._debug:
            print('posting')
        post_id = self._client.call(posts.NewPost(post))
        self.add_comments(post_id, post_id, fb_dict['comments'], ul_resources)

    def add_comments(self, post_id, parent, fb_comments, ul_resources=False):
        for fb_dict in fb_comments:
            comment = wordpress_xmlrpc.WordPressComment()
            comment.parent = parent
            comment.date_created = facebook_timestamp_to_datetime(fb_dict['created_time'])
            comment.status = 'approve'
            comment.content = fb_dict['message']
            if 'attachment' in fb_dict:
                if ul_resources:
                    fb_dict['attachment'] = self.upload(fb_dict['attachment'])
                if self._debug:
                    print('image {}'.format(fb_dict['attachment']))
                comment.content += '\n\n{}'.format(fb_dict['attachment'])
            if self._debug:
                if parent == post_id:
                    print('comment')
                else:
                    print('- comment')
            try:
                # save comment
                comment_id = self._client.call(comments.NewComment(post_id, comment))
                # rename author (has to be done separately)
                rec = wordpress_xmlrpc.WordPressComment()
                rec.author = fb_dict['from']['name']
                self._client.call(comments.EditComment(comment_id, rec))
                # handle replies
                self.add_comments(post_id, comment_id, fb_dict['comments'], ul_resources)
            except xmlrpc_client.Fault as e:
                if e.faultCode == 409:
                    if self._debug:
                        print('(duplicate)')
                    pass
                else:
                    raise
