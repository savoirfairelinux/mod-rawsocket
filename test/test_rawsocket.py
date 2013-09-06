#!/usr/bin/env python


#
from  shinken_test import *
import socket

define_modulesdir("../modules")
modulesctx.set_modulesdir(modulesdir)

# Special Livestatus module opening since the module rename
#from shinken.modules.livestatus import module as livestatus_broker
rawsocket_broker = modulesctx.get_module('raw-socket')
RawSocket_broker = rawsocket_broker.RawSocket_broker


class RawSocketTemplate(ShinkenTest):

    def do_load_modules(self):
        self.modules_manager.load_and_init()
        self.log.log("I correctly loaded the modules: [%s]" %
                     (','.join([inst.get_name() for inst in self.modules_manager.instances])))

    def update_broker(self, dodeepcopy=False):
        # The brok should be manage in the good order
        ids = self.sched.brokers['Default-Broker']['broks'].keys()
        ids.sort()
        for brok_id in ids:
            brok = self.sched.brokers['Default-Broker']['broks'][brok_id]
            #print "Managing a brok type", brok.type, "of id", brok_id
            #if brok.type == 'update_service_status':
            #    print "Problem?", brok.data['is_problem']
            if dodeepcopy:
                brok = copy.deepcopy(brok)
            manage = getattr(self.raw_socket, 'manage_' + brok.type + '_brok', None)
            if manage:
            # Be sure the brok is prepared before call it
                brok.prepare()
                manage(brok)
        self.sched.brokers['Default-Broker']['broks'] = {}

    def setUp(self, modconf=None):
        self.setup_with_file('etc/nagios_1r_1h_1s.cfg')
        self.raw_socket = RawSocket_broker(modconf)
        print "Cleaning old broks?"
        self.sched.conf.skip_initial_broks = False
        self.sched.brokers['Default-Broker'] = {'broks': {}, 'has_full_broks': False}
        self.sched.fill_initial_broks('Default-Broker')
        self.update_broker()
        self.nagios_path = None
        self.livestatus_path = None
        self.nagios_config = None
        # add use_aggressive_host_checking so we can mix exit codes 1 and 2
        # but still get DOWN state
        host = self.sched.hosts.find_by_name("test_host_0")
        host.__class__.use_aggressive_host_checking = 1
        self.sock_serv = socket.socket()
        self.sock_serv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock_serv.bind(("127.0.0.1", 12345))
        self.sock_serv.listen(1)
        self.raw_socket.init()
        self.conn_serv, _ = self.sock_serv.accept()

    def tearDown(self):
        if os.path.exists('var/nagios.log'):
            os.remove('var/nagios.log')
        if os.path.exists('var/retention.dat'):
            os.remove('var/retention.dat')
        if os.path.exists('var/status.dat'):
            os.remove('var/status.dat')
        self.conn_serv.close()
        self.sock_serv.close()
        self.raw_socket.con.close()

    def template_alert_and_notif(self, mod):
        self.print_header()

        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")

        # To make tests quicker we make notifications send very quickly
        svc.notification_interval = 0.001

        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults

        # Get the Pending => UP lines
        self.scheduler_loop(1, [[host, 0, 'UP']], do_sleep=True, sleep_time=0.1)
        self.scheduler_loop(1, [[svc, 0, 'OK']], do_sleep=True, sleep_time=0.1)
        self.update_broker()
        self.raw_socket.hook_tick("DUMMY")
        output = self.conn_serv.recv(1024)
        lines = output.splitlines()
        pattern_out0 = 'event_type="host_check_result" hostname="test_host_0" state="UP" ' \
                       'last_state="PENDING" state_type="HARD" last_state_type="HARD" ' \
                       'business_impact="5" last_hard_state_change="[0-9]{10}" output="UP'
        pattern_out1 = 'event_type="service_check_result" hostname="test_host_0" servicename="test_ok_0" ' \
                       'state="OK" last_state="PENDING" state_type="HARD" last_state_type="HARD" ' \
                       'business_impact="5" last_hard_state_change="[0-9]{10}" output="OK'
        #import pdb;pdb.set_trace()
        self.assert_(re.search(pattern_out0, lines[0]) is not None)
        self.assert_(re.search(pattern_out1, lines[1]) is not None)

        # Service 1st alert + check_result
        self.scheduler_loop(1, [[svc, 2, 'BAD']], do_sleep=True, sleep_time=0.1)
        self.update_broker()
        self.raw_socket.hook_tick("DUMMY")
        output = self.conn_serv.recv(1024)
        lines = output.splitlines()
        pattern_out0 = 'event_type="SERVICE ALERT" hostname="test_host_0" '\
                       'servicename="test_ok_0" state="CRITICAL" business_impact="5" output="BAD'
        pattern_out2 = 'event_type="service_check_result" hostname="test_host_0" ' \
                       'servicename="test_ok_0" state="CRITICAL" last_state="OK" state_type="SOFT" ' \
                       'last_state_type="HARD" business_impact="5" last_hard_state_change="[0-9]{10}" ' \
                       'output="BAD'
        #import pdb;pdb.set_trace()
        self.assert_(re.search(pattern_out0, lines[0]) is not None)
        self.assert_(re.search(pattern_out2, lines[2]) is not None)

        # Service 2nd alert + notif
        self.scheduler_loop(1, [[svc, 2, 'BAD']], do_sleep=True, sleep_time=0.1)
        self.update_broker()
        self.raw_socket.hook_tick("DUMMY")
        output = self.conn_serv.recv(1024)
        # line0 = service alert, line1 empty, line2=check result, line3 service notif
        lines = output.splitlines()
        pattern_out0 = 'event_type="SERVICE ALERT" hostname="test_host_0" '\
                       'servicename="test_ok_0" state="CRITICAL" business_impact="5" output="BAD'
        pattern_out2 = 'event_type="service_check_result" hostname="test_host_0" ' \
                       'servicename="test_ok_0" state="CRITICAL" last_state="CRITICAL" state_type="HARD" ' \
                       'last_state_type="SOFT" business_impact="5" ' \
                       'last_hard_state_change="[0-9]{10}" output="BAD'
        pattern_out3 = 'event_type="SERVICE NOTIFICATION" contact="test_contact" '\
                       'hostname="test_host_0" servicename="test_ok_0" ntype="CRITICAL" '\
                       'command="notify-service" business_impact="5" output="BAD'
        #import pdb;pdb.set_trace()
        self.assert_(re.search(pattern_out0, lines[0]) is not None)
        # check result with different type is not filtered :)
        self.assert_(re.search(pattern_out2, lines[2]))
        if mod == "all":
            # notification that is not an ack is filtered
            self.assert_(re.search(pattern_out3, lines[3]))

        # Host 1st alert
        self.scheduler_loop(1, [[host, 2, 'BAD']], do_sleep=True, sleep_time=0.1)
        self.update_broker()
        self.raw_socket.hook_tick("DUMMY")
        output = self.conn_serv.recv(1024)
        lines = output.splitlines()
        pattern_out0 = 'event_type="HOST ALERT" hostname="test_host_0" '\
                       'state="DOWN" business_impact="5" output="BAD'
        #import pdb;pdb.set_trace()
        self.assert_(re.search(pattern_out0, lines[0]) is not None)

        # Hard is 3 attempt, we just ignore the second try
        self.scheduler_loop(1, [[host, 2, 'BAD']], do_sleep=True, sleep_time=0.1)
        self.update_broker()
        self.raw_socket.hook_tick("DUMMY")
        output = self.conn_serv.recv(1024)

        self.scheduler_loop(1, [[host, 2, 'BAD']], do_sleep=True, sleep_time=0.1)
        self.update_broker()
        self.raw_socket.hook_tick("DUMMY")
        output = self.conn_serv.recv(1024)
        lines = output.splitlines()
        pattern_out0 = 'event_type="HOST ALERT" hostname="test_host_0" '\
                       'state="DOWN" business_impact="5" output="BAD'
        pattern_out2 = 'event_type="HOST NOTIFICATION" contact="test_contact" '\
                       'hostname="test_host_0" ntype="DOWN" command="notify-host" '\
                       'business_impact="5" output="BAD'
        self.assert_(re.search(pattern_out0, lines[0]) is not None)
        if mod == "all":
            self.assert_(re.search(pattern_out2, lines[3]) is not None)


class RawSocketTestAll(RawSocketTemplate):
    def setUp(self):
        modconf = Module(
            {'module_name': 'RawSocket',
             'module_type': 'raw_socket',
             'port': '12345',
             'host': '127.0.0.1',
             'data': 'all',
             'tick_limit': '3600', })
        super(RawSocketTestAll, self).setUp(modconf=modconf)

    def test_alert_and_notif(self):
        super(RawSocketTestAll, self).template_alert_and_notif("all")

    def test_reconnect(self):
        self.print_header()

        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")

        # To make tests quicker we make notifications send very quickly
        svc.notification_interval = 0.001

        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults

        self.scheduler_loop(1, [[host, 0, 'UP']], do_sleep=True, sleep_time=0.1)
        self.scheduler_loop(1, [[svc, 0, 'OK']], do_sleep=True, sleep_time=0.1)

        self.scheduler_loop(1, [[svc, 2, 'BAD']], do_sleep=True, sleep_time=0.1)

        self.raw_socket.con.close()
        self.update_broker()

        # Raise a log error log entry
        self.raw_socket.hook_tick("DUMMY")
        # Send again the buffer
        self.raw_socket.hook_tick("DUMMY")

        self.conn_serv, _ = self.sock_serv.accept()
        output = self.conn_serv.recv(1024)
        pattern_out = 'event_type="SERVICE ALERT" hostname="test_host_0" '\
                      'servicename="test_ok_0" state="CRITICAL" business_impact="5" output="BAD'
        print pattern_out, output
        self.assert_(re.search(pattern_out, output) is not None)

    def test_size_buf(self):
        self.print_header()
        fake_lines = 30 * "lines_deleted\n" + 1500 * "lines_keeped\n"
        self.raw_socket.buffer = fake_lines.splitlines()
        self.raw_socket.hook_tick("DUMMY")
        output = self.conn_serv.recv(1000000)
        self.assert_("lines_deleted" not in output)


class RawSocketTestFilter(RawSocketTemplate):
    def setUp(self):
        modconf = Module(
            {'module_name': 'RawSocket',
             'module_type': 'raw_socket',
             'port': '12345',
             'host': '127.0.0.1',
             'data': 'default',
             'tick_limit': '3600', })
        super(RawSocketTestFilter, self).setUp(modconf=modconf)

    def test_alert_and_notif(self):
        super(RawSocketTestFilter, self).template_alert_and_notif("filter")


if __name__ == '__main__':

    command = """unittest.main()"""
    unittest.main()
