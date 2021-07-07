# Microweb

[Microco.sm](http://microco.sm) is a new forum SaaS product, founded by [David Kitchen](https://twitter.com/buro9) and [Matt Cottingham](https://twitter.com/mattrco).

Communities are already using Microco.sm as their forum software of choice, such as the [Espruino Forum](http://forum.espruino.com) and [LFGSS](https://www.lfgss.com).

Microweb is the official web client for Microco.sm, written in Django. If you're not familiar with the Microcosm API, you should start by reading the [API documentation](http://microcosm-cc.github.io/).

If you find any problems, just raise an issue on github and we'll respond ASAP.

[![Build Status](https://travis-ci.org/microcosm-cc/microweb.svg?branch=master)](https://travis-ci.org/microcosm-cc/microweb)

## Project setup

To run the django project, you'll first need to create a python virtualenv by running the following:

```
virtualenv -p python2.7 envname
source envname/bin/activate
pip install -r requirements.txt
```

This will install all dependencies listed in `requirements.txt`. All commands should be executed with the virtual environment activated.

## Project structure

As is good practice with Django projects, separate apps handle different areas of functionality. For instance, the `conversations` app contains the urls and views associated with conversations.

The layout is as follows:

```
├── microweb
│   ├── comments
│   ├── conversations
│   ├── core
│   ├── events
│   ├── huddles
│   ├── microcosms
│   ├── profiles
│   ├── search
│   ├── updates
```

The `core` package contains a client for the Microcosm API. If you're familiar with Django, the rest of the packages and modules will look familiar.

## Tests

Unit tests can be run with:

```
python manage.py test
```

There is also an [integration test suite using selenium](https://github.com/microcosm-cc/microweb-integration) that runs as a standalone process.

## User authentication

Since authentication is handled by the API, custom middleware is used to provide the authentication context in views. We do this by checking the value of the `access_token` cookie.

In `core/middleware/context.py`:

```python
def process_request(self, request):
    """
    Checks for access_token cookie and appends it to the request object if present.

    All request objects have a view_requests attribute which is a list of requests
    that will be executed by grequests to fetch data for the view.
    """

    request.access_token = None
    request.whoami_url = ''
    request.view_requests = []

    if request.COOKIES.has_key('access_token'):
        request.access_token = request.COOKIES['access_token']
        request.whoami_url, params, headers = WhoAmI.build_request(request.get_host(), request.access_token)
        request.view_requests.append(grequests.get(request.whoami_url, params=params, headers=headers))

    request.site_url, params, headers = Site.build_request(request.get_host())
    request.view_requests.append(grequests.get(request.site_url, params=params, headers=headers))
```

As you can see, `request` has `view_requests` attribute which is a list of requests to be made to the API to render the view. The requests are executed concurrently using `grequests` in the views themselves (there's more work to be done here, like having a reusable connection pool, but it works well enough for now).

So on each request we make a couple of calls to the API to check if the user has a valid `access_token` cookie, and retrieve some basic site data (title, description).

## Running a development instance

If you've followed the instructions above on setting up a virtualenv, the next thing you'll need to do is fill in `local_settings.py` with your API key ([email us](mailto:founders@microcosm.cc) if you don't have one). Use [the template here](https://github.com/microcosm-cc/microweb/blob/master/microweb/local_settings.py.sample) as a guide.

If you run with `DEBUG = True` (for development only!), static files should work correctly. In production, we use nginx to serve these.

## Deploying

We use [fabric](http://www.fabfile.org/) as our deployment tool. To use this with your own instance, you'll need to modify `fabfile.py` to contain the hosts you wish to deploy to.

