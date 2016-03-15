There are some exceptions but Google search results basically are NOT case sensiteve.
This application will Google query terms (the first input box), scan through the results in a specific range (From:From+Limit) and filter out those results where the filter terms (second input box; if empty, then same as the query terms) does not appear exactly in the same case as given by the user.
Support for phrase search (quotes) has been added but no other advanced search option is supported like negative terms, etc.
If you want to use advanced search options then type your advanced Google query in the upper box and use the second input box to provide case sensitive filter terms. Example:
http://case-sensitive-search.appspot.com/search?q=%22Rose+Bush%22+site%3Afacebook.com&btn=Start&f=%22Rose+Bush%22&s=0

The user can set the maximum number of Google results that will be scanned through in the "Limit" drop down box. This is an upper limit for the depth of a search. Actually the search will stop when 10 case-matching results have been found. The user can click on the "Next" button to get the next page (continue with scaning through the Google results).

Here can you find the project source. You can leave comments here as well. Thanx for your comments.