#!/usr/bin/env python
# encoding: utf-8
import logging
import cgi
import os
import urllib
import simplejson
import sets
import re
from time import sleep
import datetime

from google.appengine.api import urlfetch
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.ext import db
from google.appengine.ext.webapp import template

import datastore_cache
datastore_cache.DatastoreCachingShim.Install()

# Set the debug level
_DEBUG = False
_SEARCHPAGESIZE = 8
_GOOGLELIMIT = 512
_PAGELIMIT = 10
_KEEPSEARCHESFORDAYS = 3
_AJAXAPIBASEURL = 'http://ajax.googleapis.com/ajax/services/search/web?v=1.0&%s&rsz=large&start='
_ENCODING = 'utf-8'

class Search(db.Model):
  """Search entity
  """
  #author = db.UserProperty()
  content = db.StringProperty() #search google with this term
  filter = db.StringProperty() #filter results case sensitively with these words
  limit = db.IntegerProperty() #stop search after found <limit> number of results; this is 10
  googlelimit = db.IntegerProperty() #scan through maximum <googlelimit> number of google results; probably will stop earlier when <limit> number of results have been found
  date = db.DateTimeProperty(auto_now_add=True) 
  start = db.IntegerProperty() #start from this result when scanning through google results
  lastresultOrd = db.IntegerProperty()  #this was the order of the last result

#http://code.google.com/apis/ajaxsearch/documentation/reference.html#_intro_fonje
class SearchResult(db.Model):
  """Search result entity
  """
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
  absoluteOrd = db.IntegerProperty()

class BaseRequestHandler(webapp.RequestHandler):
  """Base request handler extends webapp.Request handler
     It defines the generate method, which renders a Django template
     in response to a web request
  """

  def generate(self, template_name, template_values={}):
    """Generate renders and HTML template along with values
       passed to that template
       Args:
         template_name: A string that represents the name of the HTML template
         template_values: A dictionary that associates objects with a string
           assigned to that object to call in the HTML template.  The defualt
           is an empty dictionary.
    """
    values = {}
    values.update(template_values)

    # Construct the path to the template
    directory = os.path.dirname(__file__)
    path = os.path.join(directory, 'templates', template_name)

    # Respond to the request by rendering the template
    self.response.out.write(template.render(path, values, debug=_DEBUG))
    
class MainRequestHandler(BaseRequestHandler):
  """Main request handler extends BaseRequestHandler
     Handles main page request that is index.html
  """

  def get(self):
    """At this moment this returns static index.html
    """
    template_values = {}
    self.generate('index.html', template_values);


class SearchRequestHandler(BaseRequestHandler):
  """Main request handler extends BaseRequestHandler
     Handles search page request that is also based on index.html template.
     Two things are filled in the template:
     1) the search params are put back to the form inputs
     2) the search results added too
  """
  
  def renderSearchResults(self, search, searchresults):
    """Two groups of things are filled in the template:
     1) the search arguments are put back to the form inputs
     2) the search results added too
    """  
    
    #logging.info("render, search.lastresultOrd:"+str(search.lastresultOrd))
    template_values = {
      'startfrom': search.start, #/ _SEARCHPAGESIZE,
      'query': search.content.replace('"', '&quot;'),
      'filter': search.filter.replace('"', '&quot;'),
    }    
    if searchresults:
      template_values.update({ 'searchresults': searchresults, 
                               'next': searchresults[len(searchresults)-1].absoluteOrd  #search.lastresultOrd,
                               })
      
    else:
      template_values.update({ 'searchresults': "no results" })  
    return self.generate('index.html', template_values)

  def saveSearch(self):
    """Save a Search entity into the datastore
    """
    search = Search()
    startfrom = self.request.get('s')
    if startfrom:
      search.start = int(startfrom) #/ _SEARCHPAGESIZE
    else:
      search.start = 0
    #logging.info('save search.start:'+str(search.start))
    search.lastresultOrd = 0
    #search.author = users.get_current_user()
    search.content = self.request.get('q')
    #logging.info('save search.content:'+search.content)    
    search.filter = self.request.get('f')
    if not len(search.filter) or search.filter is None or search.filter == '':
      #logging.info('put search.content into search.filter!')
      search.filter = search.content
    #logging.info('save search.filter:'+search.filter)    
    googleresultslimit = self.request.get('l')
    #logging.info("save search googleresultslimit:"+googleresultslimit)
    if googleresultslimit is None or googleresultslimit == '':
      search.googlelimit = _GOOGLELIMIT
    else:
      search.googlelimit = int(googleresultslimit)
    #logging.info('save search.googlelimit:'+str(search.googlelimit))    
    search.limit = _PAGELIMIT
    search.put()
    return search

  def saveSearchResult(self, search, ord, absoluteOrd, r):
    """Save a Search result entity into the datastore
    """
    searchResult = SearchResult()
    searchResult.searchref = search.key();
    searchResult.searchresult_ord = ord
    searchResult.absoluteOrd = absoluteOrd
    searchResult.unescapedUrl = r['unescapedUrl']
    searchResult.url = r['url']
    searchResult.visibleUrl = r['visibleUrl']
    if r['cacheUrl']:
      searchResult.cacheUrl = r['cacheUrl']
    searchResult.title = r['title']
    searchResult.titleNoFormatting = r['titleNoFormatting']
    searchResult.content = r['content']
    searchResult.put()
    return searchResult

  def doSearch(self, search):
    """Do an actual search that is fetch google search result pages using Google Ajax search API
       and filter Google's results case sensitively
       Filtered results will be saved and returned in a list  
    """  
    searchResults = []
    search_terms = search.filter.replace('"', "").split()
    #logging.info('search_terms:'+str(search_terms))
    if not len(search_terms):
      #logging.info('no search_terms, return empty list')
      return searchResults  
    start = search.start / _SEARCHPAGESIZE
    ord = 0
    FUCK = 0
    absolute_ord = search.start
    q_search_term = urllib.urlencode({'q' : search.content.encode(_ENCODING)})
    url = _AJAXAPIBASEURL % (q_search_term)
    urlset = set()
    #logging.info("search range start, search.googlelimit::"+str(start)+"-"+str(search.googlelimit))
    for n in range(start, search.googlelimit):
      FUCK = FUCK + 1
      fetchurl = ''.join([url, str(n)])
      #logging.info('FUCK > FETCHURL:'+str(FUCK)+" > "+fetchurl)
      result = urlfetch.fetch(fetchurl)
      #logging.info('FETCHURL: fetched')
      results = None
      if result.status_code == 200:
        json = simplejson.loads(result.content)
        try:
          #logging.info('jsonresult:'+str(json))
          if json['responseDetails'] == 'out of range start':
            logging.warning('json error out of range start, url:'+fetchurl+'; res:'+str(json))  
            break
          if json['responseStatus'] == 200:
            results = json['responseData']['results']
        except:
          logging.warning('json error, url:'+fetchurl+'; res:'+str(json))
        if results:
          for r in results:
            absolute_ord = absolute_ord + 1
            ok = 0
            for term in search_terms:
              if (re.search(r'(>|\b)'+term+r'(\b|<)', r['content']) is not None) \
              or (re.search(r'(>|\b)'+term+r'(\b|<)', r['titleNoFormatting']) is not None) \
              or (re.search(r'(>|\b)'+term+r'(\b|<)', r['visibleUrl']) is not None):
                ok = ok + 1
            if r['url'] not in urlset:
              urlset.add(r['url'])
            else:
              ok = 0
            #logging.info('ok:'+str(ok)+' <len(search_terms):'+str(len(search_terms)))
            if ok == len(search_terms):
              ord = ord + 1
              #logging.info('save:'+str(r)) 
              searchResults.append(self.saveSearchResult(search, ord, absolute_ord, r))
      else:
        logging.warning('no response, url:'+fetchurl+'; res status code:'+str(result.status_code) + "; res.content:"+result.content)
      if ord >= search.limit:
        break
    
    #logging.info("re save search.lastresultOrd :"+str(absolute_ord))  
    search.lastresultOrd = absolute_ord
    search.save() 
    return searchResults

  def getSearchResultsFromMemoryOrDataStore(self, searchRequest):
    """Try find a similar search to the actual request which is not too old.
       If found, then return the results from the datastore
    """
    searchresults = []
    now = datetime.datetime.now()
    past = now - datetime.timedelta(days=15)
    searches = db.GqlQuery("SELECT * from Search WHERE content = :1 AND filter = :2 AND start = :3 AND date <= DATETIME(" \
                           +str(now.year)+", "+str(now.month)+", "+str(now.day)+", "+str(now.hour)+", "+str(now.minute)+", "+str(now.second)+") AND date > DATETIME(" \
                           +str(past.year)+", "+str(past.month)+", "+str(past.day)+", "+str(past.hour)+", "+str(past.minute)+", "+str(past.second) \
                           +") ORDER BY date DESC", searchRequest.content,searchRequest.filter,searchRequest.start)
    tres = 0
    search = None
    searchresultsdb = None
    for s in searches:
      if s.lastresultOrd > tres:
        tres = s.lastresultOrd
        search = s
      
    
    if search:
      #logging.info('WOW searchresults found in datastore')   
      searchresultsdb = db.GqlQuery("SELECT * FROM SearchResult WHERE searchref = :1 ORDER BY searchresult_ord ASC ",
                                  search.key())
    if searchresultsdb:
      for searchresult in searchresultsdb:
        searchresults.append(searchresult) 
    return searchresults 

    
  def get(self):
    """Here is the main idea: Lets try not to do an actual search.
       Instead, try to find `good´ results either in memory (memcache) or in datastore.
       If not found, then do an actual search.
       Finally render the results 
    """  
    searchrequest = self.saveSearch()
    searchresults = []
    try:
      searchresults = self.getSearchResultsFromMemoryOrDataStore(searchrequest)
      #logging.info("str(len(searchresults from db)):"+str(len(searchresults)))
      if len(searchresults) < 1:
        #logging.info("call do search")  
        searchresults = self.doSearch(searchrequest)
    finally:
      self.renderSearchResults(searchrequest, searchresults)


application = webapp.WSGIApplication(
                                     [('/', MainRequestHandler),
                                      ('/search', SearchRequestHandler)],
                                     debug=False)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()