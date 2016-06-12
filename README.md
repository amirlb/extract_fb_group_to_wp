# Facebook Group -> WordPress blog tool

Made for the חפירות על מתמטיקה Facebook group.

## Basic usage

Download posts:

```python
from facebook_api import *
token = 'EA...ZDZD'
# or token = open('access_token.txt').read()
api = FacebookAPI(token, 'v2.6')
group_name = 'חפירות על מתמטיקה'
group_id = list(api.search('חפירות על מתמטיקה', 'group'))[0]['id']
api.download_entire_group(group_id)
# or api.download_group_since(group_id, '2016-06-05')
```

Upload to WordPress:

```python
import wordpress_adapter
blog_address = 'https://mathematicaldeliberations.wordpress.com/'
blog_admin_username = 'admin'
blog_admin_password = '...'
adapter = wordpress_adapter.WordPressAdapter(blog_address, blog_admin_username, blog_admin_password, debug=True)
for post in PostRef.load_posts_sorted_by_id('posts')[::-1]:
    if not post.is_empty():
        print(post._updated_time)
        adapter.add_post(post, True)
```
