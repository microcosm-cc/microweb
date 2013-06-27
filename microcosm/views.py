import requests

from functools import wraps
from microweb import settings
from microweb.settings import PAGE_SIZE
from microweb.helpers import build_url
from urlparse import urlunparse

from django.core.urlresolvers import reverse
from django.core.exceptions import PermissionDenied
from django.core.exceptions import SuspiciousOperation
from django.http import Http404
from django.http import HttpResponseBadRequest
from django.http import HttpResponse
from django.http import HttpResponseNotAllowed
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.shortcuts import render_to_response
from django.template import RequestContext

from microcosm.api.exceptions import APIException
from microcosm.api.resources import Microcosm
from microcosm.api.resources import MicrocosmList
from microcosm.api.resources import User
from microcosm.api.resources import GeoCode
from microcosm.api.resources import Event
from microcosm.api.resources import Comment
from microcosm.api.resources import Conversation
from microcosm.api.resources import Profile
from microcosm.api.resources import COMMENTABLE_ITEM_TYPES

from microcosm.forms.forms import EventCreate
from microcosm.forms.forms import EventEdit
from microcosm.forms.forms import MicrocosmCreate
from microcosm.forms.forms import MicrocosmEdit
from microcosm.forms.forms import ConversationCreate
from microcosm.forms.forms import ConversationEdit
from microcosm.forms.forms import CommentForm
from microcosm.forms.forms import ProfileEdit


def exception_handler(view_func):
    """
    Decorator for view functions that raises appropriate
    errors to the user and passes data to the error view.

    Forbidden and Not Found are the only statuses that are
    communicated to the visitor. All other errors should
    be handled in client code or a generic error page will
    be displayed.
    """

    @wraps(view_func)
    def decorator(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except APIException as e:
            if e.status_code == 401:
                raise PermissionDenied
            elif e.status_code == 404:
                raise Http404
            else:
                raise
    return decorator


class ItemView(object):
    """
    A base view class that provides generic create/read/update methods and single item or list views.
    This class shouldn't be used directly, it should be subclassed.
    """

    @classmethod
    @exception_handler
    def create(cls, request, microcosm_id=None):
        """
        Generic method for creating microcosms and items within microcosms.

        microcosm_id only needs to be provided if an item is being created
        within a microcosm (e.g. a conversation or event).
        """

        view_data = {
            'user': request.whoami,
            'site': request.site,
        }

        # Populate form from POST data, return populated form if not valid
        if request.method == 'POST':
            form = cls.create_form(request.POST)
            if form.is_valid():
                item = cls.resource_cls.create(
                    request.META['HTTP_HOST'],
                    form.cleaned_data,
                    request.access_token
                )
                return HttpResponseRedirect('/%s/%d' % (cls.item_plural, item['id']))
            else:
                view_data['form'] = form
                return render(request, cls.form_template, view_data)

        # Render form for creating a new item
        elif request.method == 'GET':
            initial = {}
            # If a microcosm_id is provided, this must be pre-populated in the item form
            if microcosm_id:
                initial['microcosmId'] = microcosm_id
            view_data['form'] = cls.create_form(initial=initial)
            return render(request, cls.form_template, view_data)

        else:
            return HttpResponseNotAllowed(['GET', 'POST'])

    @classmethod
    @exception_handler
    def edit(cls, request, item_id):
        """
        Generic edit view. The item with item_id is used to populate form fields.
        """

        view_data = {
            'user': request.whoami,
            'site': request.site,
        }

        # Populate form from POST data, return populated form if not valid
        if request.method == 'POST':
            form = cls.edit_form(request.POST)
            if form.is_valid():
                form_data = form.cleaned_data
                # API expects editReason wrapped in a 'meta' object
                if form_data.has_key('editReason'):
                    form_data['meta'] =  {'editReason': form_data['editReason']}
                item = cls.resource_cls.update(request.META['HTTP_HOST'], form_data, item_id, request.access_token)
                return HttpResponseRedirect('/%s/%d' % (cls.item_plural, item['id']))
            else:
                view_data['form'] = form
                return render(request, cls.form_template, view_data)

        # Populate form with item data
        elif request.method == 'GET':
            item = cls.resource_cls.retrieve(request.META['HTTP_HOST'], id=item_id, access_token=request.access_token)
            view_data['form'] = cls.edit_form(item)
            return render(request, cls.form_template, view_data)

        else:
            return HttpResponseNotAllowed(['GET', 'POST'])

    @classmethod
    @exception_handler
    def single(cls, request, item_id):
        """
        Generic method for displaying a single item.
        """

        # Offset for paging of item comments
        offset = int(request.GET.get('offset', 0))

        content = cls.resource_cls.retrieve(
            request.META['HTTP_HOST'],
            id=item_id,
            offset=offset,
            access_token=request.access_token
        )

        view_data = {
            'user': request.whoami,
            'site': request.site,
            'item_type': cls.item_type,
            'content': content,
            'pagination': {},
        }

        # Provide a comment form for items that allow comments
        if cls.commentable:
            comment_form = CommentForm(
                initial = {
                    'itemId': item_id,
                    'itemType': cls.item_type,
                }
            )
            view_data['comment_form'] = comment_form

        # Composition of any other elements, e.g. attendees or poll choices
        if hasattr(cls, 'extra_item_data') and callable(cls.extra_item_data):
            view_data = cls.extra_item_data(
                request,
                item_id,
                view_data,
                request.access_token
            )

        return render(request, cls.one_template, view_data)

    @classmethod
    @exception_handler
    def list(cls, request):
        """
        Generic method for displaying a list of items.
        """

        # Pagination offset
        offset = int(request.GET.get('offset', 0))

        list = cls.resource_cls.retrieve(request.META['HTTP_HOST'], offset=offset, access_token=request.access_token)

        view_data = {
            'user': request.whoami,
            'site': request.site,
            'content': list,
            'pagination': {},
        }

        return render(request, cls.many_template, view_data)

    @classmethod
    @exception_handler
    def delete(cls, request, item_id):
        """
        Generic method for deleting a single item (deletion of a list is not yet implemented).
        """

        if request.method == 'POST':
            cls.resource_cls.delete(request.META['HTTP_HOST'], item_id, request.access_token)
            # item deletion
            if request.POST.has_key('microcosm_id') and request.POST['microcosm_id'] != "":
                microcosm_id = int(request.POST['microcosm_id'])
                redirect = reverse(MicrocosmView.single, args=(microcosm_id,))
            # comment deletion
            # TODO: to be replaced with item mappings
            elif request.POST.has_key('item_type'):
                if request.POST['item_type'] not in ['event', 'conversation']:
                    raise SuspiciousOperation
                redirect = '/%ss/%d' % (request.POST['item_type'], int(request.POST['item_id']))
            else:
                redirect = reverse(MicrocosmView.list)
            return HttpResponseRedirect(redirect)
        else:
            return HttpResponseNotAllowed()

class ConversationView(ItemView):

    item_type = 'conversation'
    item_plural = 'conversations'
    resource_cls = Conversation
    create_form = ConversationCreate
    edit_form = ConversationEdit
    form_template = 'forms/conversation.html'
    one_template = 'conversation.html'
    commentable = True


class ProfileView(ItemView):

    item_type = 'profile'
    item_plural = 'profiles'
    edit_form = ProfileEdit
    form_template = 'forms/profile.html'
    single_template = 'profile.html'

    @staticmethod
    @exception_handler
    def single(request, profile_id):
        """
        Generic method for displaying a single item.
        """

        view_data = dict(user=request.whoami, site=request.site)

        profile = Profile.retrieve(
            request.META['HTTP_HOST'],
            profile_id,
            request.access_token
        )

        view_data['content'] = profile

        return render(request, ProfileView.single_template, view_data)

    @staticmethod
    @exception_handler
    def edit(request, profile_id):
        """
        To edit a Profile, we must fetch the associated User object since the
        user's email is submitted as Profile.gravatar. This won't be needed when
        PATCH support is added.
        """

        view_data = dict(user=request.whoami, site=request.site)

        if request.method == 'POST':
            form = ProfileView.edit_form(request.POST)
            if form.is_valid():
                form_data = Profile(form.cleaned_data)
                profile = Profile.update(
                    request.META['HTTP_HOST'],
                    form_data.as_dict,
                    profile_id,
                    request.access_token
                )
                return HttpResponseRedirect(reverse('single-profile', args=(profile['id'],)))
            else:
                view_data['form'] = form
                return render(request, ProfileView.form_template, view_data)

        elif request.method == 'GET':
            user_private_details = User.retrieve(
                request.META['HTTP_HOST'],
                request.whoami.user_id,
                access_token=request.access_token
            )
            user_profile = Profile.retrieve(
                request.META['HTTP_HOST'],
                profile_id,
                request.access_token
            )
            user_profile.gravatar = user_private_details.email
            view_data['form'] = ProfileView.edit_form(user_profile.as_dict)
            return render(request, ProfileView.form_template, view_data)

        else:
            return HttpResponseNotAllowed(['GET', 'POST'])


def build_pagination_links(request, paged_list):

    """
    Builds page navigation links based on the request path
    and links supplied in the paginated list.
    """

    page_nav = {}

    if paged_list.links.get('first'):
        page_nav['first'] = request.path

    if paged_list.links.get('prev'):
        offset = paged_list.offset
        page_nav['prev'] = urlunparse(('', '', request.path, '', 'offset=%d' % (offset - PAGE_SIZE), '',))

    if paged_list.links.get('next'):
        offset = paged_list.offset
        page_nav['next'] = urlunparse(('', '', request.path, '', 'offset=%d' % (offset + PAGE_SIZE), '',))

    if paged_list.links.get('last'):
        offset = paged_list.max_offset
        page_nav['last'] = urlunparse(('', '', request.path, '', 'offset=%d' % offset, '',))

    return page_nav


class MicrocosmView(ItemView):

    create_form = MicrocosmCreate
    edit_form = MicrocosmEdit
    form_template = 'forms/microcosm.html'
    single_template = 'microcosm.html'
    list_template = 'microcosms.html'

    @staticmethod
    @exception_handler
    def single(request, microcosm_id):

        # record offset for paging of items within the microcosm
        offset = int(request.GET.get('offset', 0))

        microcosm = Microcosm.retrieve(
            request.META['HTTP_HOST'],
            id=microcosm_id,
            offset=offset,
            access_token=request.access_token
        )

        view_data = {
            'user': request.whoami,
            'site': request.site,
            'content': microcosm,
            'pagination': build_pagination_links(request, microcosm.items)
        }

        return render(request, MicrocosmView.single_template, view_data)

    @staticmethod
    @exception_handler
    def list(request):

        # record offset for paging of microcosms
        offset = int(request.GET.get('offset', 0))

        microcosm_list = MicrocosmList.retrieve(
            request.META['HTTP_HOST'],
            offset=offset,
            access_token=request.access_token
        )

        view_data = {
            'user': request.whoami,
            'site': request.site,
            'content': microcosm_list,
            'pagination': build_pagination_links(request, microcosm_list.microcosms)
        }

        return render(request, MicrocosmView.list_template, view_data)

    @staticmethod
    @exception_handler
    def create(request):

        view_data = {
            'user': request.whoami,
            'site': request.site,
        }

        if request.method == 'POST':
            form = MicrocosmView.create_form(request.POST)
            if form.is_valid():
                microcosm = Microcosm.create(
                    request.META['HTTP_HOST'],
                    form.cleaned_data,
                    request.access_token
                )
                return HttpResponseRedirect(reverse('single-microcosm', args=(microcosm['id'],)))
            else:
                view_data['form'] = form
                return render(request, MicrocosmView.form_template, view_data)

        elif request.method == 'GET':
            view_data['form'] = MicrocosmView.create_form()
            return render(request, MicrocosmView.form_template, view_data)

        else:
            return HttpResponseNotAllowed(['GET', 'POST'])

    @classmethod
    @exception_handler
    def create_item_choice(cls, request, microcosm_id):
        """
        Interstitial page for creating an item (e.g. Event) belonging to a microcosm.
        """

        microcosm = cls.resource_cls.retrieve(
            request.META['HTTP_HOST'],
            microcosm_id,
            access_token=request.access_token
        )

        view_data = {
            'user' : request.whoami,
            'site' : request.site,
            'content' : microcosm
        }

        return render(request, 'create_item_choice.html', view_data)


class EventView(ItemView):

    item_type = 'event'
    item_plural = 'events'
    resource_cls = Event
    create_form = EventCreate
    edit_form = EventEdit
    form_template = 'forms/event.html'
    one_template = 'event.html'
    commentable = True

    @classmethod
    def extra_item_data(cls, request, event_id, view_data, access_token=None):
        view_data['attendees'] = cls.resource_cls.retrieve_attendees(
            request.META['HTTP_HOST'],
            event_id,
            access_token
        )
        return view_data

    @classmethod
    def rsvp(cls, request, event_id):
        """
        Create an attendee (RSVP) for an event. An attendee can be in one of four states:
        invited, confirmed, maybe, no.
        """

        if request.method == 'POST':
            if request.whoami:
                attendee = {
                    'RSVP' : request.POST['rsvp'],
                    'AttendeeId' : request.whoami['id']
                }
                cls.resource_cls.rsvp(
                    request.META['HTTP_HOST'],
                    event_id,
                    request.whoami['id'],
                    attendee,
                    access_token=request.access_token
                )
                return HttpResponseRedirect('/events/%s' % event_id)
            else:
                raise PermissionDenied
        else:
            raise HttpResponseNotAllowed(['POST'])


class CommentView(ItemView):

    item_type = 'comment'
    item_plural = 'comments'
    resource_cls = Comment
    create_form = CommentForm
    edit_form = CommentForm
    form_template = 'forms/create_comment.html'
    one_template = 'comment.html'

    @staticmethod
    def fill_from_get(request, initial):
        """
        Populating comment form fields from GET parameters
        """

        if request.GET.has_key('itemId'):
            initial['itemId'] = int(request.GET.get('itemId', None))
        if request.GET.has_key('itemType'):
            if request.GET['itemType'] not in COMMENTABLE_ITEM_TYPES:
                raise ValueError
            initial['itemType'] = request.GET.get('itemType', None)
        if request.GET.has_key('inReplyTo'):
            initial['inReplyTo'] = int(request.GET.get('inReplyTo', None))

        return initial

    @classmethod
    @exception_handler
    def create(cls, request):
        """
        Comment forms populate attributes from GET parameters, so require the create
        method to be extended.
        """

        view_data = {
            'user': request.whoami,
            'site': request.site,
        }

        if request.method == 'POST':
            form = cls.create_form(request.POST)
            if form.is_valid():
                item = cls.resource_cls.create(
                    request.META['HTTP_HOST'],
                    data=form.cleaned_data,
                    access_token=request.access_token
                )

                # If a 'via' link is returned, go to that page and comment fragment
                if item['meta'].has_key('linkmap') and item['meta']['linkmap'].has_key('via'):
                    if 'offset' in item['meta']['linkmap']['via']:
                        offset = item['meta']['linkmap']['via'].split('offset=')[1]
                        return HttpResponseRedirect('/%ss/%d?offset=%s#comment%d' %
                            (item['itemType'], item['itemId'], offset, item['id']))
                    else:
                        return HttpResponseRedirect('/%ss/%d#comment%d' % (item['itemType'], item['itemId'], item['id']))
                else:
                    return HttpResponseRedirect('/%s/%d' % (cls.item_plural, item['id']))
            else:
                view_data['form'] = form
                return render(request, cls.form_template, view_data)

        elif request.method == 'GET':
            initial = CommentView.fill_from_get(request, {})
            view_data['form'] = cls.create_form(initial=initial)
            return render(request, cls.form_template, view_data)

        else:
            return HttpResponseNotAllowed(['GET', 'POST'])

    @classmethod
    @exception_handler
    def edit(cls, request, item_id):
        """
        Comment forms populate attributes from GET parameters, so require the create
        method to be extended.
        """

        view_data = {
            'user': request.whoami,
            'site': request.site,
        }

        if request.method == 'POST':
            form = cls.create_form(request.POST)
            if form.is_valid():
                item = cls.resource_cls.update(
                    request.META['HTTP_HOST'],
                    form.cleaned_data,
                    item_id,
                    request.access_token
                )

                # If a 'via' link is returned, go to that page and comment fragment
                if item['meta'].has_key('linkmap') and item['meta']['linkmap'].has_key('via'):
                    if 'offset' in item['meta']['linkmap']['via']:
                        offset = item['meta']['linkmap']['via'].split('offset=')[1]
                        return HttpResponseRedirect('/%ss/%d?offset=%s#comment%d' %
                            (item['itemType'], item['itemId'], offset, item['id']))
                    else:
                        return HttpResponseRedirect('/%ss/%d#comment%d' % (item['itemType'], item['itemId'], item['id']))
                else:
                    return HttpResponseRedirect(''.join(['/', cls.item_plural, '/', str(item['id'])]))
            else:
                view_data['form'] = form
                return render(request, cls.form_template, view_data)

        elif request.method == 'GET':
            comment = cls.resource_cls.retrieve(
                request.META['HTTP_HOST'],
                item_id,
                access_token=request.access_token
            )
            view_data['form'] = cls.edit_form(comment)
            return render(request, cls.form_template, view_data)

        else:
            return HttpResponseNotAllowed(['GET', 'POST'])


class ErrorView():

    @staticmethod
    def not_found(request):

        view_data = {
            'site' : request.site,
            'user' : request.whoami,
        }
        return render(request, '404.html', view_data)

    @staticmethod
    def forbidden(request):

        view_data = {
            'site' : request.site,
            'user' : request.whoami,
        }
        return render(request, '403.html', view_data)

    @staticmethod
    def server_error(request):
        return render_to_response('500.html',
            context_instance = RequestContext(request)
        )


class AuthenticationView():

    @staticmethod
    @exception_handler
    def login(request):
        """
        Log a user in. Creates an access_token using a persona
        assertion and the client secret. Sets this access token as a cookie.
        'target_url' based as a GET parameter determines where the user is
        redirected.
        """

        target_url = request.POST.get('target_url')
        assertion = request.POST.get('Assertion')
        client_secret = settings.CLIENT_SECRET

        data = {
            "Assertion": assertion,
            "ClientSecret": client_secret
        }
        headers= {'Host': request.META.get('HTTP_HOST')}

        access_token = requests.post(build_url(request.META['HTTP_HOST'], ['auth']), data=data, headers=headers).json()['data']

        response = HttpResponseRedirect(target_url if target_url != '' else '/')
        response.set_cookie('access_token', access_token, httponly=True)
        return response

    @staticmethod
    @exception_handler
    def logout(request):
        """
        Log a user out. Issues a DELETE request to the backend for the
        user's access_token, and issues a delete cookie header in response to
        clear the user's access_token cookie.
        """

        view_data = {
            'site': request.site,
        }

        response = render(request, 'logout.html', view_data)

        if request.COOKIES.has_key('access_token'):
            response.delete_cookie('access_token')
            url = build_url(request.META['HTTP_HOST'], ['auth',request.access_token])
            requests.post(url, params={'method': 'DELETE', 'access_token': request.access_token})

        return response


class GeoView():

    @staticmethod
    @exception_handler
    def geocode(request):
        if request.access_token is None:
            raise PermissionDenied
        if request.GET.has_key('q'):
            response = GeoCode.retrieve(
                request.META['HTTP_HOST'],
                request.GET['q'],
                request.access_token
            )
            return HttpResponse(response, content_type='application/json')
        else:
            return HttpResponseBadRequest()


def echo_headers(request):
    view_data = '<html><body><table>'
    for key in request.META.keys():
        view_data += '<tr><td>%s</td><td>%s</td></tr>' % (key, request.META[key])
    view_data += '</table></body></html>'
    return HttpResponse(view_data, content_type='text/html')
