mod-rawsocket
=============
What is it?
-----------

This  broker module is made to export some data to a socket. It can be used to send data to another log system such as log stash or splunk.

The data is formatted the following way : 
```
<priority>date source source-ip process-name[facility]: key="value" [key="value"]*
```
This is related to RFC 3164, http://tools.ietf.org/html/rfc3164

Note – Date : RFC3164 does not enforce the date format, we use a standard date format. 
```
ISO 8601 formatted date : "yyyy−mm−ddThh:mi:sszzzzzz" (ex : 1997−07−16T19:20:30+01:00)
```


How does it work ?
----------------

As all broker modules, this modules has fuctions to handle brok regarding the brok's type. For now, only data from the following fuctions are used :
* manage_log_brok : parse alert, notification, flapping and downtime. 
* manage_host_check_result_brok : generates a new line in the buffer. Used to compute SLA
* manage_service_check_result_brok : generates a new line in the buffer. Used to compute SLA

* manage_initial_host_status_brok : Update the business_impact mapping
* manage_initial_service_status_brok : Update the business_impact mapping
* manage_update_host_status_brok : Update the business_impact mapping
* manage_update_service_status_brok : Update the business_impact mapping


Configuration
--------------
Edit the config in etc to match what you want.

The data paramater is all or "something-else". If all is specified, it will not filter log envent to send. If so it will only send the following log event : host and service alert (hard and soft), host and service downtime (started and stopped), host and service notification acknowledgment.

It is always better to keep everything and ignore what we do not need, but it's up to the user. For now the list in only configurable by editing the python code, there is no way to speficy it in the configuration


