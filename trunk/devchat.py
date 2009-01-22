import logging
import cgi
import os
import urllib
import simplejson
import sets
import re
from time import sleep

from google.appengine.api import urlfetch
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.ext import db
from google.appengine.ext.webapp import template
#from google.appengine.api import memcache

# Set the debug level
_DEBUG = True

class Search(db.Model):
  author = db.UserProperty()
  content = db.StringProperty()
  limit = db.IntegerProperty()
  googlelimit = db.IntegerProperty()
  date = db.DateTimeProperty(auto_now_add=True)

#http://code.google.com/apis/ajaxsearch/documentation/reference.html#_intro_fonje
class SearchResult(db.Model):
  searchref = db.ReferenceProperty(Search)
  searchresult_ord = db.IntegerProperty()
  unescapedUrl = db.LinkProperty()
  url = db.LinkProperty()
  visibleUrl = db.StringProperty()
  cacheUrl = db.LinkProperty()
  title = db.StringProperty()
  titleNoFormatting = db.StringProperty()
  content = db.StringProperty()
  date = db.DateTimeProperty(auto_now_add=True)

class BaseRequestHandler(webapp.RequestHandler):
  """Base request handler extends webapp.Request handler

     It defines the generate method, which renders a Django template
     in response to a web request
  """

  def generate(self, template_name, template_values={}):
    """Generate takes renders and HTML template along with values
       passed to that template

       Args:
         template_name: A string that represents the name of the HTML template
         template_values: A dictionary that associates objects with a string
           assigned to that object to call in the HTML template.  The defualt
           is an empty dictionary.
    """
    # We check if there is a current user and generate a login or logout URL
    user = users.get_current_user()

    if user:
      log_in_out_url = users.create_logout_url('/')
      url = users.create_logout_url(self.request.uri)
      url_linktext = 'Logout'
    else:
      log_in_out_url = users.create_login_url(self.request.path)
      url = users.create_login_url(self.request.uri)
      url_linktext = 'Login'


    # We'll display the user name if available and the URL on all pages
    values = {
      'url': url,
      'url_linktext': url_linktext,
      'user': user, 
      'log_in_out_url': log_in_out_url
      }
    values.update(template_values)

    # Construct the path to the template
    directory = os.path.dirname(__file__)
    path = os.path.join(directory, 'templates', template_name)

    # Respond to the request by rendering the template
    self.response.out.write(template.render(path, values, debug=_DEBUG))
    
class MainRequestHandler(BaseRequestHandler):
  def get(self):

    template_values = {}

    self.generate('index.html', template_values);


class SearchRequestHandler(BaseRequestHandler):
  def renderSearchResults(self, search):
    searchresults = db.GqlQuery("SELECT * FROM SearchResult WHERE searchref = :1 ORDER BY searchresult_ord ASC ",
                                    search.key())
    template_values = {
      'searchterm': search.content,
      'searchresults': searchresults
    }
    return self.generate('searchresults.html', template_values)


  def post(self):
    search = Search()
    search.author = users.get_current_user()
    search_term = self.request.get('searchtext')
    search.content = search_term
    googleresultslimit = self.request.get('googleresultslimit')
    end = int(googleresultslimit) #20
    if end is None:
      end = 16
    search.googlelimit = end
    limit = int(self.request.get('resultslimit')) #12
    if limit is None:
      limit = 8
    search.limit = limit
    search.put()
    start = 0
    ord = 0
    q_search_term = urllib.urlencode({'q' : search_term.encode('utf-8')})
    url = 'http://ajax.googleapis.com/ajax/services/search/web?v=1.0&%s&rsz=large&start=' % (q_search_term)
    urlset = set()
    for n in range(start, end):
      if ord > limit:
        break
      fetchurl = ''.join([url, str(n)])
      #logging.info('FETCHURL:'+fetchurl)
      result = urlfetch.fetch(fetchurl)
      #logging.info('FETCHURL: fetched')
      results = None
      if result.status_code == 200:
        json = simplejson.loads(result.content)
        try:
          #logging.info('jsonresult:'+str(json))
          if json['responseDetails'] == 'out of range start':
            break
          if json['responseStatus'] == 200:
            results = json['responseData']['results']
        except:
          logging.warning('json error, url:'+fetchurl+'; res:'+str(json))

        if results:
          search_term = search_term.replace('"', "")
          search_terms = search_term.split()
          for r in results:
            ok = 0
            for term in search_terms:
              if (re.search(r'(>|\b)'+term+r'(\b|<)', r['content']) is not None) \
              or (re.search(r'(>|\b)'+term+r'(\b|<)', r['titleNoFormatting']) is not None) \
              or (re.search(r'(>|\b)'+term+r'(\b|<)', r['visibleUrl']) is not None):
                ok = 1
            if r['url'] not in urlset:
              urlset.add(r['url'])
            else:
              ok = 0
            if ok:
              searchResult = SearchResult()
              searchResult.searchref = search.key();
              ord = ord + 1
              searchResult.searchresult_ord = ord
              searchResult.unescapedUrl = r['unescapedUrl']
              searchResult.url = r['url']
              searchResult.visibleUrl = r['visibleUrl']
              if r['cacheUrl']:
                searchResult.cacheUrl = r['cacheUrl']
              searchResult.title = r['title']
              searchResult.titleNoFormatting = r['titleNoFormatting']
              searchResult.content = r['content']
              searchResult.put()
    self.renderSearchResults(search)


# 
#class ChatsRequestHandler(BaseRequestHandler):
#  def renderChats(self):
#    greetings_query = Greeting.all().order('date')
#    greetings = greetings_query.fetch(1000)

# #    template_values = {
#      'greetings': greetings,
#    }
#    return self.generate('chats.html', template_values)
#      
#  def getChats(self, useCache=True):
#    if useCache is False:
#      greetings = self.renderChats()
#      if not memcache.set("chat", greetings, 10):
#        logging.error("Memcache set failed:")
#      return greetings
#      
#    greetings = memcache.get("chats")
#    if greetings is not None:
#      return greetings
#    else:
#      greetings = self.renderChats()
#      if not memcache.set("chat", greetings, 10):
#        logging.error("Memcache set failed:")
#      return greetings
#    
#  def get(self):
#    self.getChats()

# #  def post(self):
#    greeting = Greeting()
#
#    if users.get_current_user():
#      greeting.author = users.get_current_user()

#    greeting.content = self.request.get('content')
#    greeting.put()
#    
#    self.getChats(False)

#    
application = webapp.WSGIApplication(
                                     [('/', MainRequestHandler),
                                      ('/getsearchresults', SearchRequestHandler)],
                                     debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()