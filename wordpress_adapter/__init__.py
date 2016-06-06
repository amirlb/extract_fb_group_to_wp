import html
import unicodedata
import time
import datetime
import pytz
import wordpress_xmlrpc
from wordpress_xmlrpc.methods import posts

DEFAULT_TEXT_DIRECTION = 'ltr'
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
            divs.append('<div></div>')
        else:
            line_bidi = unicodedata.bidirectional(line.strip()[0])
            if line_bidi == 'L':
                direction = 'ltr'
            elif line_bidi == 'R':
                direction = 'rtl'
            divs.append(div_with_direction(line, direction))
    return '<br />\n'.join(divs)


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

    def __init__(self, blog_name, username, password):
        rpc_url = 'https://{}.wordpress.com/xmlrpc.php'.format(blog_name)
        self._client = wordpress_xmlrpc.Client(rpc_url, username, password)

    def post_from_fb(self, fb_dict):
        post = wordpress_xmlrpc.WordPressPost()
        post.title = extract_title(fb_dict['message'])
        post.content = format_message(fb_dict['message'])
        if fb_dict['pictures']:
            images = ''.join('<img src="{}" />\n'.format(url) for url in fb_dict['pictures'])
            post.content = images + post.content
            # post.thumbnail = fb_dict['pictures'][0]
        post.date = facebook_timestamp_to_datetime(fb_dict['created_time'])
        if fb_dict['updated_time'] != fb_dict['created_time']:
            post.date_modified = facebook_timestamp_to_datetime(fb_dict['updated_time'])
        post.terms_names = {'post_tag': [fb_dict['from']['name']]}
        post.post_status = 'publish'
        self._client.call(posts.NewPost(post))
