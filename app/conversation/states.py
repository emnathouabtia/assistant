from enum import Enum


class State(str, Enum):
    IDLE = "idle"
    PARSING = "parsing"
    NEEDS_INFO = "needs_info"
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    DEPLOYING = "deploying"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "canceled"

TERMINAL = {State.DONE, State.FAILED, State.CANCELLED}
ALLOWED ={ 
    State.IDLE : {State.PARSING},
    State.PARSING : {State.NEEDS_INFO, State.PLANNING, State.IDLE},
    State.NEEDS_INFO : {State.PARSING, State.CANCELLED},
    State.PLANNING : {State.AWAITING_CONFIRMATION, State.FAILED},
    State.AWAITING_CONFIRMATION : {State.DEPLOYING, State.PARSING, State.CANCELLED},
    State.DEPLOYING : {State.DONE, State.FAILED},
    State.DONE : {State.IDLE},
    State.FAILED : {State.IDLE},
    State.CANCELLED : {State.IDLE}

}
def can_move(current:State ,new:State) -> bool:
    return new in ALLOWED[current]
