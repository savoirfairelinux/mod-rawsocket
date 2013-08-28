#!/usr/bin/python

# -*- coding: utf-8 -*-

# Copyright (C) 2009-2013:
# Gabes Jean, naparuba@gmail.com
# Gerhard Lausser, Gerhard.Lausser@consol.de
# Gregory Starck, g.starck@gmail.com
# Hartmut Goebel, h.goebel@goebel-consult.de
# Francois Mikus, fmikus@acktomic.com
# Savoir-Faire Linux inc.
#
# This file is part of Shinken.
#
# Shinken is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Shinken is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with Shinken. If not, see <http://www.gnu.org/licenses/>.


# This Class is a plugin for the Shinken Broker. It is responsible
# for sending log broks to a raw socket destination.

import re
import socket
import time
import datetime

from shinken.basemodule import BaseModule
from shinken.log import logger

properties = {
    'daemons': ['broker'],
    'type': 'raw_socket',
    'external': False,
    'phases': ['running'],
}


# called by the plugin manager to get a broker
def get_instance(plugin):
    logger.info("Get a RawSocket broker for plugin %s" % plugin.get_name())

    #Catch errors
    #path = plugin.path
    instance = RawSocket_broker(plugin)
    return instance


# Get broks and send them to TCP Raw Socket listener
class RawSocket_broker(BaseModule):
    def __init__(self, modconf):
        BaseModule.__init__(self, modconf)
        self.host = getattr(modconf, 'host', 'localhost')
        self.port = int(getattr(modconf, 'port', '9514'))
        self.data = getattr(modconf, 'data', 'default')
        self.tick_limit = int(getattr(modconf, 'tick_limit', '3600'))
        self.buffer = []
        self.ticks = 0
        # Cache for business_impact
        self.dict_business_impact = {}
        # Buffer max size in bytes
        self.max_buffer_size = 60000
        # Number of lines to delete when the buffer is full
        self.lines_deleted = 30
        # For log brok only, to select only some event to send to socket.
        self.event_list = [("host_alert", "HARD"),
                           ("host_alert", "SOFT"),
                           ("service_alert", "HARD"),
                           ("service_alert", "SOFT"),
                           ("host_downtime", "STARTED"),
                           ("host_downtime", "STOPPED"),
                           ("service_downtime", "STARTED"),
                           ("service_downtime", "STOPPED"),
                           ("host_notification", "ACKNOWLEDGEMENT"),
                           ("service_notification", "ACKNOWLEDGEMENT"),
                           ("comment", None)]

        # properties for log event. Every log line has its own data. The list_param is listing them
        # the pattern is what the output looks like.
        self.parsing_properties = {
            'host_alert': {
                'pattern': 'event_type="%(event_type)s" hostname="%(hostname)s" state="%(state)s"'
                           ' business_impact="%(business_impact)d" output="%(output)s"',
                'list_params': ["hostname", "state", "state_type", "attempt", "output"]},
            'service_alert': {
                'pattern': 'event_type="%(event_type)s" hostname="%(hostname)s" '
                           'servicename="%(servicename)s" state="%(state)s"'
                           ' business_impact="%(business_impact)d" output="%(output)s"',
                'list_params': ["hostname", "servicename", "state", "state_type", "attempt", "output"]},
            'host_downtime_alert': {
                'pattern': 'event_type="%(event_type)s" hostname="%(hostname)s" state="%(state)s"'
                           ' business_impact="%(business_impact)d" output="%(output)s"',
                'list_params': ["hostname", "state", "output"]},
            'service_downtime_alert': {
                'pattern': 'event_type="%(event_type)s" hostname="%(hostname)s"'
                           ' servicename="%(servicename)s" state="%(state)s"'
                           ' business_impact="%(business_impact)d" output="%(output)s"',
                'list_params': ["hostname", "servicename", "state", "output"]},
            'host_flapping_alert': {
                'pattern': 'event_type="%(event_type)s" hostname="%(hostname)s" state="%(state)s"'
                           ' business_impact="%(business_impact)d" output="%(output)s"',
                'list_params': ["hostname", "state", "output"]},
            'service_flapping_alert': {
                'pattern': 'event_type="%(event_type)s" hostname="%(hostname)s"'
                           ' servicename="%(servicename)s" state="%(state)s"'
                           ' business_impact="%(business_impact)d" output="%(output)s"',
                'list_params': ["hostname", "servicename", "state", "output"]},
            'host_notification': {
                'pattern': 'event_type="%(event_type)s" contact="%(contact)s"'
                           ' hostname="%(hostname)s" ntype="%(ntype)s" command="%(command)s"'
                           ' business_impact="%(business_impact)d" output="%(output)s"',
                'list_params': ["contact", "hostname", "ntype", "command", "output"]},
            'service_notification': {
                'pattern': 'event_type="%(event_type)s" contact="%(contact)s"'
                           ' hostname="%(hostname)s" servicename="%(servicename)s"'
                           ' ntype="%(ntype)s" command="%(command)s"'
                           ' business_impact="%(business_impact)d" output="%(output)s"',
                'list_params': ["contact", "hostname", "servicename", "ntype", "command", "output"]},
            'add_svc_comment': {
                'pattern': 'event_type="%(event_type)s" message="Not Handled yet"',
                'list_params': []},
            'add_host_comment': {
                'pattern': 'event_type="%(event_type)s" message="Not Handled yet"',
                'list_params': []},
            'event_handler': {
                'pattern': 'event_type="%(event_type)s" message="Not Handled yet"',
                'list_params': []}
        }

    # Try to connect to host, port
    def init(self):
        try:
            self.con = socket.socket()
            self.con.connect((self.host, self.port))
        except Exception:
            logger.warning("[RawSocket broker] Failed to connect to host %s and port %d!"
                           % (self.host, self.port))

    # Parse the line and create and dict of key values.
    # Return the formatted line and timestamp
    def format_output(self, line, pattern, list_params):
        t, line = line.split('] ', 1)
        event_type, data = line.split(': ', 1)
        # Creates key-values dict
        l_params = dict(zip(list_params, data.split(';', max(len(list_params) - 1, 0))))
        # Add event type and business impact in the dict because all lines generated need it
        l_params["event_type"] = event_type
        key_search = l_params["hostname"]
        if "service_description" in l_params:
            key_search += "::" + l_params["service_description"]
        l_params["business_impact"] = self.dict_business_impact[key_search]
        return t, pattern % l_params

    # For log event only : return the event_name associated in the parsing properties
    def build_name(self, group):
        name = ""
        for elem in group:
            if elem:
                name += "_" + elem.lower()
        return name[1:]

    # For log event only : add to the buffer the converted log line into the new format
    def parse_event(self, name, etype, line):
        if self.data == 'all' or (name, etype) in self.event_list:
            if name in self.parsing_properties.keys():
                t, new_line = self.format_output(line, **self.parsing_properties[name])
                t = t[1:]
                formatted = datetime.datetime.fromtimestamp(int(t)).strftime('%Y-%m-%dT%H:%M')
                tz = str.format('{0:+06.2f}', float(time.timezone) / 3600).replace('.', ':')
                isodate = formatted + tz
                hostname = socket.gethostname()
                self.buffer.append("<0>" + isodate + " " + hostname + " " +
                                   socket.gethostbyname(hostname) + " " +
                                   self.name + "[0]: " + new_line)

            else:
                logger.info("Can't parse event : %s. Skipping" % name)
        else:
            logger.info("Unhandled event : %s. I skipped the following line : %s"
                        % (name, etype))

    # Matches lines with pattern to define the event
    # A log brok has arrived, we UPDATE data info with this
    def manage_log_brok(self, b):
        data = b.data
        line = data['log']

        patterns = [
            "^\[[0-9]*\] (HOST|SERVICE) (ALERT):.*;(HARD|SOFT);.*",
            "^\[[0-9]*\] (HOST|SERVICE) (NOTIFICATION):.*;(ACKNOWLEDGEMENT)?.*",
            "^\[[0-9]*\] (HOST|SERVICE) (FLAPPING) (ALERT):.*;(STARTED|STOPPED);",
            "^\[[0-9]*\] (HOST|SERVICE) (DOWNTIME) (ALERT):.*;(STARTED|STOPPED|CANCELLED);",
            "^\[[0-9]*\] (HOST|SERVICE) (EVENT) (HANDLER):.*(NONE)?.*",
            #"EXTERNAL COMMAND: (ADD_HOST_COMMENT|ADD_SVC_COMMENT)",  # FIXME : No timestamp
        ]

        for pattern in patterns:
            matches = re.search(pattern, line)
            if matches:
                groups = matches.groups()
                name = self.build_name(groups[:-1])
                self.parse_event(name, groups[-1], line)
                return

        logger.debug("Unmanaged log line : %s" % line)

    def hook_tick(self, brok):
        """Each second the broker calls the hook_tick function
        Every tick try to flush the buffer
        """

        if self.buffer == []:
            return

        # Todo : why we need this?
        if self.ticks >= self.tick_limit:
            # If the number of ticks where data was not
            # sent successfully to the raw socket reaches the buffer limit.
            # Reset the buffer and reset the ticks
            self.buffer = []
            self.ticks = 0
            return

        # Real memory size
        if sum(x.__sizeof__() for x in self.buffer) > self.max_buffer_size:
            logger.debug("[RawSocket broker]Buffer size exceeded. I delete %d lines"
                         % self.lines_deleted)
            self.buffer = self.buffer[self.lines_deleted:]

        self.ticks += 1

        try:
            self.con.sendall('\n'.join(self.buffer).encode('UTF-8') + '\n')
        except IOError, err:
            logger.error("[RawSocket broker] Failed sending to the Raw network socket! IOError:%s"
                         % str(err))
            self.init()
            return
        except Exception, err:
            logger.error("[RawSocket broker] Failed sending to socket! Error:%s" % str(err))
            self.init()
            return

        # Flush the buffer after a successful send to the Raw Socket
        self.buffer = []
        self.ticks = 0

    def manage_clean_all_my_instance_id_brok(self, b):
        pass

    def manage_program_status_brok(self, b):
        pass

    def manage_update_program_status_brok(self, b):
        pass

    def manage_initial_host_status_brok(self, b):
        # Remember initial business_impact value
        self.dict_business_impact[b.data["host_name"]] = b.data["business_impact"]

    def manage_initial_service_status_brok(self, b):
        # Remember initial business_impact value
        key = b.data["host_name"] + "::" + b.data["service_description"]
        self.dict_business_impact[key] = b.data["business_impact"]

    def manage_initial_hostgroup_status_brok(self, b):
        pass

    def manage_initial_servicegroup_status_brok(self, b):
        pass

    def manage_host_check_result_brok(self, b):
        if self.data == 'all':
            data = b.data
            # get the business_impact previously found and add it to the brok
            data["business_impact"] = self.dict_business_impact[data["host_name"]]
            new_line = 'event_type="host_check_result" ' \
                       'hostname="%(host_name)s" state="%(state)s" last_state="%(last_state)s" ' \
                       'business_impact="%(business_impact)d" ' \
                       'last_hard_state_change="%(last_hard_state_change)s" output="%(output)s"' \
                       % data
            formatted = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M')
            tz = str.format('{0:+06.2f}', float(time.timezone) / 3600).replace('.', ':')
            isodate = formatted + tz
            hostname = socket.gethostname()
            self.buffer.append("<0>" + isodate + " " + hostname + " " +
                               socket.gethostbyname(hostname) + " " +
                               self.name + "[0]: " + new_line)

    def manage_host_next_schedule_brok(self, b):
        pass

    def manage_service_check_result_brok(self, b):
        if self.data == 'all':
            data = b.data
            # get the business_impact previously found and add it to the brok
            key = data["host_name"] + "::" + data["service_description"]
            data["business_impact"] = self.dict_business_impact[key]
            new_line = 'event_type="service_check_result" hostname="%(host_name)s" ' \
                       'servicename="%(service_description)s" state="%(state)s" ' \
                       'business_impact="%(business_impact)d" last_state="%(last_state)s" ' \
                       'last_hard_state_change="%(last_hard_state_change)s" output="%(output)s"' \
                       % data
            formatted = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M')
            tz = str.format('{0:+06.2f}', float(time.timezone) / 3600).replace('.', ':')
            isodate = formatted + tz
            hostname = socket.gethostname()
            self.buffer.append("<0>" + isodate + " " + hostname + " " +
                               socket.gethostbyname(hostname) + " " +
                               self.name + "[0]: " + new_line)

    def manage_service_next_schedule_brok(self, b):
        pass

    def manage_update_host_status_brok(self, b):
        # Update business_impact value
        self.dict_business_impact[b.data["host_name"]] = b.data["business_impact"]

    def manage_update_service_status_brok(self, b):
        # Update business_impact value
        key = b.data["host_name"] + "::" + b.data["service_description"]
        self.dict_business_impact[key] = b.data["business_impact"]

    def manage_initial_contact_status_brok(self, b):
        pass

    def manage_initial_contactgroup_status_brok(self, b):
        pass

    def manage_notification_raise_brok(self, b):
        pass
