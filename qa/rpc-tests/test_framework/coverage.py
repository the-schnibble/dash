"""
This module contains utilities for doing coverage analysis on the RPC
interface.

It provides a way to track which RPC commands are exercised during
testing.

"""
import os


REFERENCE_FILENAME = 'rpc_interface.txt'


class AuthServiceProxyWrapper(object):
    """
    An object that wraps AuthServiceProxy to record specific RPC calls.

    """
    def __init__(self, auth_service_proxy_instance, coverage_logfile=None):
        """
        Kwargs:
            auth_service_proxy_instance (AuthServiceProxy): the instance
                being wrapped.
            coverage_logfile (str): if specified, write each service_name
                out to a file when called.

        """
        self.auth_service_proxy_instance = auth_service_proxy_instance
        self.coverage_logfile = coverage_logfile
        
        # memoize calls to some dashd methods
        self.governance_info = None
        self.gobject_votes = {}

    def __getattr__(self, *args, **kwargs):
        return_val = self.auth_service_proxy_instance.__getattr__(
            *args, **kwargs)

        return AuthServiceProxyWrapper(return_val, self.coverage_logfile)

    def __call__(self, *args, **kwargs):
        """
        Delegates to AuthServiceProxy, then writes the particular RPC method
        called to a file.

        """
        return_val = self.auth_service_proxy_instance.__call__(*args, **kwargs)
        rpc_method = self.auth_service_proxy_instance._service_name

        if self.coverage_logfile:
            with open(self.coverage_logfile, 'a+') as f:
                f.write("%s\n" % rpc_method)

        return return_val

    @property
    def url(self):
        return self.auth_service_proxy_instance.url


    #
    # dash specific methods
    #
    
    @property
    def rpc_connection(self):
        return self

    @classmethod
    def from_dash_conf(self, dash_dot_conf):
        from dash_config import DashConfig
        config_text = DashConfig.slurp_config_file(dash_dot_conf)
        creds = DashConfig.get_rpc_creds(config_text, config.network)

        return self(**creds)

    def rpc_command(self, *params):
        return self.rpc_connection.__getattr__(params[0])(*params[1:])

    # common RPC convenience methods
    def is_testnet(self):
        return self.rpc_command('getinfo')['testnet']

    def get_masternodes(self):
        mnlist = self.rpc_command('masternodelist', 'full')
        return [Masternode(k, v) for (k, v) in mnlist.items()]

    def get_object_list(self):
        try:
            golist = self.rpc_command('gobject', 'list')
        except JSONRPCException as e:
            golist = self.rpc_command('mnbudget', 'show')
        return golist

    def get_current_masternode_vin(self):
        from dashlib import parse_masternode_status_vin

        my_vin = None

        try:
            status = self.rpc_command('masternode', 'status')
            my_vin = parse_masternode_status_vin(status['vin'])
        except JSONRPCException as e:
            pass

        return my_vin

    def governance_quorum(self):
        # TODO: expensive call, so memoize this
        total_masternodes = self.rpc_command('masternode', 'count', 'enabled')
        min_quorum = self.govinfo['governanceminquorum']

        # the minimum quorum is calculated based on the number of masternodes
        quorum = max(min_quorum, (total_masternodes // 10))
        return quorum

    @property
    def govinfo(self):
        if (not self.governance_info):
            self.governance_info = self.rpc_command('getgovernanceinfo')
        return self.governance_info

    # governance info convenience methods
    def superblockcycle(self):
        return self.govinfo['superblockcycle']

    def governanceminquorum(self):
        return self.govinfo['governanceminquorum']

    def proposalfee(self):
        return self.govinfo['proposalfee']

    def last_superblock_height(self):
        height = self.rpc_command('getblockcount')
        cycle = self.superblockcycle()
        return cycle * (height // cycle)

    def next_superblock_height(self):
        return self.last_superblock_height() + self.superblockcycle()

    def is_masternode(self):
        return not (self.get_current_masternode_vin() is None)

    def is_synced(self):
        mnsync_status = self.rpc_command('mnsync', 'status')
        synced = (mnsync_status['IsBlockchainSynced'] and
                  mnsync_status['IsMasternodeListSynced'] and
                  mnsync_status['IsWinnersListSynced'] and
                  mnsync_status['IsSynced'] and
                  not mnsync_status['IsFailed'])
        return synced

    def current_block_hash(self):
        height = self.rpc_command('getblockcount')
        block_hash = self.rpc_command('getblockhash', height)
        return block_hash

    def get_superblock_budget_allocation(self, height=None):
        if height is None:
            height = self.rpc_command('getblockcount')
        return Decimal(self.rpc_command('getsuperblockbudget', height))

    def next_superblock_max_budget(self):
        cycle = self.superblockcycle()
        current_block_height = self.rpc_command('getblockcount')

        last_superblock_height = (current_block_height // cycle) * cycle
        next_superblock_height = last_superblock_height + cycle

        last_allocation = self.get_superblock_budget_allocation(last_superblock_height)
        next_allocation = self.get_superblock_budget_allocation(next_superblock_height)

        next_superblock_max_budget = next_allocation

        return next_superblock_max_budget

    # "my" votes refers to the current running masternode
    # memoized on a per-run, per-object_hash basis
    def get_my_gobject_votes(self, object_hash):
        import dashlib
        if not self.gobject_votes.get(object_hash):
            my_vin = self.get_current_masternode_vin()
            # if we can't get MN vin from output of `masternode status`,
            # return an empty list
            if not my_vin:
                return []

            (txid, vout_index) = my_vin.split('-')

            cmd = ['gobject', 'getcurrentvotes', object_hash, txid, vout_index]
            raw_votes = self.rpc_command(*cmd)
            self.gobject_votes[object_hash] = dashlib.parse_raw_votes(raw_votes)

        return self.gobject_votes[object_hash]

    def is_govobj_maturity_phase(self):
        # 3-day period for govobj maturity
        maturity_phase_delta = 1662      # ~(60*24*3)/2.6
        if config.network == 'testnet':
            maturity_phase_delta = 24    # testnet

        event_block_height = self.next_superblock_height()
        maturity_phase_start_block = event_block_height - maturity_phase_delta

        current_height = self.rpc_command('getblockcount')
        event_block_height = self.next_superblock_height()

        # print "current_height = %d" % current_height
        # print "event_block_height = %d" % event_block_height
        # print "maturity_phase_delta = %d" % maturity_phase_delta
        # print "maturity_phase_start_block = %d" % maturity_phase_start_block

        return (current_height >= maturity_phase_start_block)

    def we_are_the_winner(self):
        import dashlib
        # find the elected MN vin for superblock creation...
        current_block_hash = self.current_block_hash()
        mn_list = self.get_masternodes()
        winner = dashlib.elect_mn(block_hash=current_block_hash, mnlist=mn_list)
        my_vin = self.get_current_masternode_vin()

        # print "current_block_hash: [%s]" % current_block_hash
        # print "MN election winner: [%s]" % winner
        # print "current masternode VIN: [%s]" % my_vin

        return (winner == my_vin)

    @property
    def MASTERNODE_WATCHDOG_MAX_SECONDS(self):
        # note: self.govinfo is already memoized
        return self.govinfo['masternodewatchdogmaxseconds']

    @property
    def SENTINEL_WATCHDOG_MAX_SECONDS(self):
        return (self.MASTERNODE_WATCHDOG_MAX_SECONDS // 2)

    def estimate_block_time(self, height):
        """
        Called by block_height_to_epoch if block height is in the future.
        Call `block_height_to_epoch` instead of this method.

        DO NOT CALL DIRECTLY if you don't want a "Oh Noes." exception.
        """
        current_block_height = self.rpc_command('getblockcount')
        diff = height - current_block_height

        if (diff < 0):
            raise Exception("Oh Noes.")

        future_minutes = 2.62 * diff
        future_seconds = 60 * future_minutes
        estimated_epoch = int(time.time() + future_seconds)

        return estimated_epoch

    def block_height_to_epoch(self, height):
        """
        Get the epoch for a given block height, or estimate it if the block hasn't
        been mined yet. Call this method instead of `estimate_block_time`.
        """
        epoch = -1

        try:
            bhash = self.rpc_command('getblockhash', height)
            block = self.rpc_command('getblock', bhash)
            epoch = block['time']
        except JSONRPCException as e:
            if e.message == 'Block height out of range':
                epoch = self.estimate_block_time(height)
            else:
                print("error: %s" % e)
                raise e

        return epoch



def get_filename(dirname, n_node):
    """
    Get a filename unique to the test process ID and node.

    This file will contain a list of RPC commands covered.
    """
    pid = str(os.getpid())
    return os.path.join(
        dirname, "coverage.pid%s.node%s.txt" % (pid, str(n_node)))


def write_all_rpc_commands(dirname, node):
    """
    Write out a list of all RPC functions available in `bitcoin-cli` for
    coverage comparison. This will only happen once per coverage
    directory.

    Args:
        dirname (str): temporary test dir
        node (AuthServiceProxy): client

    Returns:
        bool. if the RPC interface file was written.

    """
    filename = os.path.join(dirname, REFERENCE_FILENAME)

    if os.path.isfile(filename):
        return False

    help_output = node.help().split('\n')
    commands = set()

    for line in help_output:
        line = line.strip()

        # Ignore blanks and headers
        if line and not line.startswith('='):
            commands.add("%s\n" % line.split()[0])

    with open(filename, 'w') as f:
        f.writelines(list(commands))

    return True
