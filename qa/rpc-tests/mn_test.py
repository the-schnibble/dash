#!/usr/bin/env python2
#
# Distributed under the MIT/X11 software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#

from test_framework.mininode import *
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import *
import time



class MNCheckRateTest(BitcoinTestFramework):
    def add_options(self, parser):
        parser.add_option("--testbinary", dest="testbinary",
                          default=os.getenv("DASHD", "dashd"),
                          help="bitcoind binary to test")

    def setup_chain(self):
        
        initialize_chain_mn(self.options.tmpdir)
       
        time.sleep(5)

    def setup_network(self):

        self.nodes = []
        for i in range(14):
            self.nodes.append(start_node(i, self.options.tmpdir, ["-externalip=127.0.0.1 -debug"]))

        for i in range(14):
            #for j in range(i,14):
            for j in range(14):
                if i != j:
                    connect_nodes(self.nodes[i], j)

        sync_masternodes(self.nodes)

    def run_test(self):

        time.sleep(10000)

if __name__ == '__main__':
    MNCheckRateTest().main()
