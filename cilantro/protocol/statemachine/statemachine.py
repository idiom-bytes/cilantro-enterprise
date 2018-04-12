from cilantro.protocol.statemachine.state import State, EmptyState


class StateMachine:
    """
    TODO -- docstring
    """
    _STATES = None
    _INIT_STATE = None

    def __init__(self):
        """
        TODO -- docstring
        """
        self.is_started = False

        assert self._STATES is not None, "_STATES is None (did you set it in the subclass?)"
        assert self._INIT_STATE is not None, "_INIT_STATE is None (did you set it in the subclass?)"

        self.state = EmptyState(self)
        self.states = None

    def start(self):
        assert not self.is_started, "StateMachine already started -- .start() must only be invoked once."

        states = self._STATES
        init_state = self._INIT_STATE

        self.states = {s: s(self) for s in states}
        assert init_state in self.states, "Init state {} not in states {}".format(init_state, self.states)

        self.is_started = True
        self.transition(init_state)

    """
    NOTE: with this approach all internal attributes of each state persist between transitions.
    Is this what we want? or should each state be dealloc'd on exit(...) and alloc a new state before enter(...)?
    """
    def transition(self, next_state: type(State)):
        """
        TODO -- docstring
        :param next_state:
        :return:
        """
        # print("\n---- STARTING TRANSITION -----")
        # print("StateMachine transition to state: ", next_state)
        assert next_state in self.states, "Next state {} not in states {}".format(next_state, self.states)
        ns = self.states[next_state]

        self.state.exit(ns)
        ns.enter(self.state)
        self.state = ns
        self.state.run()

        # print("\n---- ENDING TRANSITION -----")