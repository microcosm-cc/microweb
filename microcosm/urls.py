from django.conf.urls import url
from django.conf.urls import patterns

from microcosm.views import UpdateView
from microcosm.views import WatcherView
from microcosm.views import UpdatePreferenceView
from microcosm.views import CommentView
from microcosm.views import ProfileView
from microcosm.views import AuthenticationView
from microcosm.views import ErrorView
from microcosm.views import FaviconView
from microcosm.views import RobotsView
from microcosm.views import SearchView
from microcosm.views import TrendingView
from microcosm.views import LegalView
from microcosm.views import ModerationView


urlpatterns = patterns('',

    # Static
    url(r'^robots\.txt$', RobotsView.as_view()),
    url(r'^favicon\.ico$', FaviconView.as_view()),

    # Auth
    url(r'^login/$', AuthenticationView.login, name='login'),
    url(r'^logout/$', AuthenticationView.logout, name='logout'),

    # Comments
    url(r'comments/create/$', CommentView.create, name='create-comment'),
    url(r'comments/(?P<comment_id>\d+)/$', CommentView.single, name='single-comment'),
    url(r'comments/(?P<comment_id>\d+)/edit/$', CommentView.edit, name='edit-comment'),
    url(r'comments/(?P<comment_id>\d+)/delete/$', CommentView.delete, name='delete-comment'),
    url(r'comments/(?P<comment_id>\d+)/incontext/$', CommentView.incontext, name='incontext-comment'),
    url(r'comments/(?P<comment_id>\d+)/source/$', CommentView.source, name='source-comment'),
    url(r'comments/(?P<comment_id>\d+)/attachments/$', CommentView.attachments, name='attachment-comment'),

    # Updates
    url(r'^updates/$', UpdateView.list, name='list-updates'),
    url(r'^updates/settings/$', UpdatePreferenceView.settings, name='updates-settings'),

    # Watchers
    url(r'^watchers/$', WatcherView.single, name='single-watcher'),

    # User profiles
    url(r'^profiles/$', ProfileView.list, name='list-profiles'),
    url(r'^profiles/(?P<profile_id>\d+)/$', ProfileView.single, name='single-profile'),
    url(r'^profiles/(?P<profile_id>\d+)/edit/$', ProfileView.edit, name='edit-profile'),

    # Search
    url(r'^search/$', SearchView.single, name='single-search'),

    # Trending
    url(r'^trending/$', TrendingView.list, name='list-trending'),

    # Legal
    url(r'^about/$', LegalView.list, name='list-legal'),
    url(r'^about/(?P<doc_name>[a-z]+)/$', LegalView.single, name='single-legal'),

    # Moderation
    url(r'^moderate/$', ModerationView.item, name='moderate-item'),

    # Echoes request headers
    url(r'^headers/', 'microcosm.views.echo_headers'),

    # Break things
    url(r'error/', ErrorView.server_error),
    url(r'notfound/', ErrorView.not_found),
    url(r'forbidden/', ErrorView.forbidden),
)
