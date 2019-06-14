delegate_list = Variable()
masternode_list = Variable()
witness_list = Variable()
notifier_list = Variable()
scheduler_list = Variable()

stamps_enabled = Variable()
nonces_enabled = Variable()
fluctuating_quorum_enabled = Variable()



@construct
def seed(masternodes,
         delegates,
         stamps=True,
         nonces=False,
         fluctuating_quorums=True):

    masternode_list.set(masternodes)
    delegate_list.set(delegates)
    witness_list.set([])
    notifier_list.set([])
    scheduler_list.set([])

    stamps_enabled.set(stamps)
    nonces_enabled.set(nonces)
    fluctuating_quorum_enabled.set(fluctuating_quorums)

@export
def get_delegates():
    return delegate_list.get()


@export
def get_masternodes():
    return masternode_list.get()


@export
def get_witnesses():
    return witness_list.get()

@export
def get_notifiers():
    return notifier_list.get()


@export
def get_schedulers():
    return scheduler_list.get()


@export
def get_stamps_enabled():
    return stamps_enabled.get()


@export
def get_nonces_enabled():
    return nonces_enabled.get()


@export
def get_fluctuating_quorum_enabled():
    return fluctuating_quorum_enabled.get()


@export
def get_boot_quorum_masternodes():
    return len(masternode_list.get())
