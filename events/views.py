import datetime
import grequests
import json

from urllib import urlencode

from urlparse import parse_qs
from urlparse import urlparse
from urlparse import urlunparse

from django.core.urlresolvers import reverse
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError

from django.http import HttpResponseRedirect
from django.http import HttpResponseBadRequest
from django.http import HttpResponse

from django.shortcuts import render

from django.views.decorators.http import require_http_methods

from microcosm.views import exception_handler
from microcosm.views import require_authentication
from microcosm.views import process_attachments
from microcosm.views import build_pagination_links

from microcosm.api.exceptions import APIException
from microcosm.api.resources import Event
from microcosm.api.resources import AttendeeList
from microcosm.api.resources import Comment
from microcosm.api.resources import Profile
from microcosm.api.resources import Attachment
from microcosm.api.resources import response_list_to_dict
from microcosm.api.resources import Site
from microcosm.api.resources import GeoCode

from microcosm.forms.forms import EventCreate
from microcosm.forms.forms import EventEdit

from microcosm.forms.forms import CommentForm

class EventView(object):
    create_form = EventCreate
    edit_form = EventEdit
    form_template = 'forms/event.html'
    single_template = 'event.html'
    comment_form = CommentForm

    @staticmethod
    @exception_handler
    @require_http_methods(['GET',])
    def single(request, event_id):
        """
        Display a single event with comments and attendees.
        """

        # Comment offset.
        offset = int(request.GET.get('offset', 0))

        # Create request for event resource.
        event_url, event_params, event_headers = Event.build_request(request.get_host(), id=event_id,
            offset=offset, access_token=request.access_token)
        request.view_requests.append(grequests.get(event_url, params=event_params, headers=event_headers))

        # Create request for event attendees.
        att_url, att_params, att_headers = Event.build_attendees_request(request.get_host(), event_id,
            request.access_token)
        request.view_requests.append(grequests.get(att_url, params=att_params, headers=att_headers))

        # Perform requests and instantiate view objects.
        responses = response_list_to_dict(grequests.map(request.view_requests))
        event = Event.from_api_response(responses[event_url])
        comment_form = CommentForm(initial=dict(itemId=event_id, itemType='event'))

        user = Profile(responses[request.whoami_url], summary=False) if request.whoami_url else None

        attendees = AttendeeList(responses[att_url])
        attendees_yes = []
        attendees_invited = []
        user_is_attending = False

        for attendee in attendees.items.items:
            if attendee.rsvp == 'yes':
                attendees_yes.append(attendee)
                if request.whoami_url:
                    if attendee.profile.id == user.id:
                        user_is_attending = True
            elif attendee.rsvp == 'maybe':
                attendees_invited.append(attendee)

        # Determine whether the event spans more than one day and if it has expired.
        # TODO: move stuff that is purely rendering to the template.
        today = datetime.datetime.now()
        end_date = event.when + datetime.timedelta(minutes=event.duration)

        is_same_day = False
        if end_date.strftime('%d%m%y') == event.when.strftime('%d%m%y'):
            is_same_day = True
        event_dates = {
            'type': 'multiple' if not is_same_day else 'single',
            'end': end_date
        }
        is_expired = True if int(end_date.strftime('%s')) < int(today.strftime('%s')) else False

        # Why is this a minimum of 10%?
        rsvp_percentage = event.rsvp_percentage
        if len(attendees_yes) and event.rsvp_percentage < 10:
            rsvp_percentage = 10

        # Fetch attachments for all comments on this page.
        # TODO: the code that does this should be in one place.
        attachments = {}
        for comment in event.comments.items:
            c = comment.as_dict
            if 'attachments' in c:
                c_attachments = Attachment.retrieve(request.get_host(), "comments", c['id'],
                    access_token=request.access_token)
                attachments[str(c['id'])] = c_attachments

        view_data = {
            'user': user,
            'site': Site(responses[request.site_url]),
            'content': event,
            'comment_form': comment_form,
            'pagination': build_pagination_links(responses[event_url]['comments']['links'], event.comments),
            'item_type': 'event',

            'attendees': attendees,
            'attendees_yes': attendees_yes,
            'attendees_invited': attendees_invited,
            'user_is_attending': user_is_attending,

            'event_dates': event_dates,

            'rsvp_num_attending': len(attendees_yes),
            'rsvp_num_invited': len(attendees_invited),
            'rsvp_percentage': rsvp_percentage,

            'is_expired': is_expired,
            'attachments': attachments
        }

        return render(request, EventView.single_template, view_data)

    @staticmethod
    @exception_handler
    @require_authentication
    @require_http_methods(['GET', 'POST',])
    def create(request, microcosm_id):
        """
        Create an event within a microcosm.
        """

        responses = response_list_to_dict(grequests.map(request.view_requests))
        view_data = {
            'user': Profile(responses[request.whoami_url], summary=False),
            'site': Site(responses[request.site_url]),
            }
        user = Profile(responses[request.whoami_url], summary=False) if request.whoami_url else None

        if request.method == 'POST':
            form = EventView.create_form(request.POST)
            if form.is_valid():
                event_request = Event.from_create_form(form.cleaned_data)
                event_response = event_request.create(request.get_host(), request.access_token)
                # invite attendees
                invites = request.POST.get('invite')
                if len(invites.strip()) > 0:
                    invited_list = invites.split(",")
                    attendees = []
                    if len(invited_list) > 0:
                        for userid in invited_list:
                            if userid != "":
                                attendees.append({
                                    'rsvp': 'maybe',
                                    'profileId': int(userid)
                                })
                        if len(attendees) > 0:
                            Event.rsvp(request.get_host(), event_response.id, user.id, attendees,
                                access_token=request.access_token)

                # create comment
                if request.POST.get('firstcomment') and len(request.POST.get('firstcomment')) > 0:
                    payload = {
                        'itemType': 'event',
                        'itemId': event_response.id,
                        'markdown': request.POST.get('firstcomment'),
                        'inReplyTo': 0
                    }
                    comment_req = Comment.from_create_form(payload)
                    comment = comment_req.create(request.get_host(), request.access_token)

                    try:
                        process_attachments(request, comment)
                    except ValidationError:
                        responses = response_list_to_dict(grequests.map(request.view_requests))
                        comment_form = CommentForm(
                            initial={
                                'itemId': comment.item_id,
                                'itemType': comment.item_type,
                                'comment_id': comment.id,
                                'markdown': request.POST['markdown'],
                                })
                        view_data = {
                            'user': Profile(responses[request.whoami_url], summary=False),
                            'site': Site(responses[request.site_url]),
                            'content': comment,
                            'comment_form': comment_form,
                            'error': 'Sorry, one of your files was over 5MB. Please try again.',
                            }
                        return render(request, EventView.form_template, view_data)

                return HttpResponseRedirect(reverse('single-event', args=(event_response.id,)))

            else:
                view_data['form'] = form
                view_data['microcosm_id'] = microcosm_id
                return render(request, EventView.form_template, view_data)

        if request.method == 'GET':
            view_data['form'] = EventView.create_form(initial=dict(microcosmId=microcosm_id))
            view_data['microcosm_id'] = microcosm_id
            return render(request, EventView.form_template, view_data)


    @staticmethod
    @exception_handler
    @require_authentication
    @require_http_methods(['GET', 'POST',])
    def edit(request, event_id):
        """
        Edit an event.
        """

        responses = response_list_to_dict(grequests.map(request.view_requests))
        view_data = {
            'user': Profile(responses[request.whoami_url], summary=False),
            'site': Site(responses[request.site_url]),
            'state_edit': True
        }

        if request.method == 'POST':
            form = EventView.edit_form(request.POST)
            if form.is_valid():
                event_request = Event.from_edit_form(form.cleaned_data)
                event_response = event_request.update(request.get_host(), request.access_token)
                return HttpResponseRedirect(reverse('single-event', args=(event_response.id,)))
            else:
                view_data['form'] = form
                view_data['microcosm_id'] = form['microcosmId']

                return render(request, EventView.form_template, view_data)

        if request.method == 'GET':
            event = Event.retrieve(request.get_host(), id=event_id, access_token=request.access_token)
            view_data['form'] = EventView.edit_form.from_event_instance(event)
            view_data['microcosm_id'] = event.microcosm_id

            # fetch attendees
            view_data['attendees'] = Event.get_attendees(host=request.get_host(), id=event_id,
                access_token=request.access_token)

            attendees_json = []
            for attendee in view_data['attendees'].items.items:
                attendees_json.append({
                    'id': attendee.profile.id,
                    'profileName': attendee.profile.profile_name,
                    'avatar': attendee.profile.avatar,
                    'sticky': 'true'
                })

            if len(attendees_json) > 0:
                view_data['attendees_json'] = json.dumps(attendees_json)
                print view_data['attendees_json']

            return render(request, EventView.form_template, view_data)


    @staticmethod
    @exception_handler
    @require_authentication
    @require_http_methods(['POST',])
    def delete(request, event_id):
        """
        Delete an event and be redirected to the parent microcosm.
        """

        event = Event.retrieve(request.get_host(), event_id, access_token=request.access_token)
        event.delete(request.get_host(), request.access_token)
        return HttpResponseRedirect(reverse('single-microcosm', args=(event.microcosm_id,)))


    @staticmethod
    @exception_handler
    @require_authentication
    @require_http_methods(['GET', ])
    def newest(request, event_id):
        """
        Get redirected to the first unread post in a conversation
        """
        response = Event.newest(request.get_host(), event_id, access_token=request.access_token)
        # Because redirects are always followed, we can't just use Location.
        response = response['comments']['links']
        for link in response:
            if link['rel'] == 'self':
                response = link['href']
        response = str.replace(str(response), '/api/v1', '')
        pr = urlparse(response)
        queries = parse_qs(pr[4])
        frag = ""
        if queries.get('comment_id'):
            frag = 'comment' + queries['comment_id'][0]
            del queries['comment_id']
            # queries is a dictionary of 1-item lists (as we don't re-use keys in our query string).
        # urlencode will encode the lists into the url (offset=[25]) etc. So get the values straight.
        for (key, value) in queries.items():
            queries[key] = value[0]
        queries = urlencode(queries)
        response = urlunparse((pr[0], pr[1], pr[2], pr[3], queries, frag))
        return HttpResponseRedirect(response)


    @staticmethod
    @exception_handler
    @require_authentication
    @require_http_methods(['POST',])
    def rsvp(request, event_id):
        """
        Create an attendee (RSVP) for an event. An attendee can be in one of four states:
        invited, yes, maybe, no.
        """
        responses = response_list_to_dict(grequests.map(request.view_requests))
        user = Profile(responses[request.whoami_url], summary=False)

        attendee = [dict(rsvp=request.POST['rsvp'],profileId=user.id),]
        try:
            Event.rsvp(request.get_host(), event_id, user.id, attendee, access_token=request.access_token)
        except APIException:
            # TODO: return forbidden response with error detail
            raise PermissionDenied

        return HttpResponseRedirect(reverse('single-event', args=(event_id,)))


class GeoView(object):
    @staticmethod
    @exception_handler
    def geocode(request):
        if request.access_token is None:
            raise PermissionDenied
        if request.GET.has_key('q'):
            response = GeoCode.retrieve(
                request.get_host(),
                request.GET['q'],
                request.access_token
            )
            return HttpResponse(response, content_type='application/json')
        else:
            return HttpResponseBadRequest()