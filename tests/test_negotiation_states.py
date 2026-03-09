"""Tests for Negotiation state machine — transitions, terminal states, messages."""

import pytest
from src.negotiation.states import Negotiation, NegotiationState, TRANSITIONS, TERMINAL_STATES


class TestNegotiationState:
    def test_all_states_defined(self):
        assert len(NegotiationState) == 10

    def test_terminal_states(self):
        expected = {
            NegotiationState.REJECTED,
            NegotiationState.TIMEOUT,
            NegotiationState.CONFIRMED,
            NegotiationState.DECLINED,
        }
        assert TERMINAL_STATES == expected

    def test_terminal_states_have_no_transitions(self):
        for state in TERMINAL_STATES:
            assert len(TRANSITIONS.get(state, set())) == 0


class TestNegotiationTransitions:
    def test_init_to_proposed(self):
        neg = Negotiation(our_url="http://a", their_url="http://b",
                          our_name="A", their_name="B", match_score=0.5)
        assert neg.can_transition_to(NegotiationState.PROPOSED)
        neg.transition(NegotiationState.PROPOSED)
        assert neg.state == NegotiationState.PROPOSED

    def test_init_cannot_go_to_accepted(self):
        neg = Negotiation(our_url="http://a", their_url="http://b",
                          our_name="A", their_name="B", match_score=0.5)
        assert not neg.can_transition_to(NegotiationState.ACCEPTED)

    def test_invalid_transition_raises(self):
        neg = Negotiation(our_url="http://a", their_url="http://b",
                          our_name="A", their_name="B", match_score=0.5)
        with pytest.raises(ValueError, match="Invalid transition"):
            neg.transition(NegotiationState.CONFIRMED)

    def test_proposed_to_evaluating(self):
        neg = Negotiation(our_url="http://a", their_url="http://b",
                          our_name="A", their_name="B", match_score=0.5)
        neg.transition(NegotiationState.PROPOSED)
        assert neg.can_transition_to(NegotiationState.EVALUATING)

    def test_accepted_to_owner_review(self):
        neg = Negotiation(our_url="http://a", their_url="http://b",
                          our_name="A", their_name="B", match_score=0.5)
        neg.transition(NegotiationState.PROPOSED)
        neg.transition(NegotiationState.EVALUATING)
        neg.transition(NegotiationState.ACCEPTED)
        assert neg.can_transition_to(NegotiationState.OWNER_REVIEW)

    def test_owner_review_to_confirmed(self):
        neg = Negotiation(our_url="http://a", their_url="http://b",
                          our_name="A", their_name="B", match_score=0.5)
        neg.transition(NegotiationState.PROPOSED)
        neg.transition(NegotiationState.EVALUATING)
        neg.transition(NegotiationState.ACCEPTED)
        neg.transition(NegotiationState.OWNER_REVIEW)
        neg.transition(NegotiationState.CONFIRMED)
        assert neg.state == NegotiationState.CONFIRMED
        assert neg.is_terminal


class TestNegotiationData:
    def _make_neg(self):
        return Negotiation(our_url="http://a", their_url="http://b",
                           our_name="A", their_name="B", match_score=0.5)

    def test_default_id_generated(self):
        neg = self._make_neg()
        assert len(neg.id) == 8

    def test_add_message(self):
        neg = self._make_neg()
        neg.add_message("http://a", "Hello", "proposal")
        assert len(neg.messages) == 1
        assert neg.messages[0].content == "Hello"
        assert neg.current_round == 1

    def test_is_terminal_false_for_init(self):
        neg = self._make_neg()
        assert neg.is_terminal is False

    def test_to_dict_structure(self):
        neg = self._make_neg()
        d = neg.to_dict()
        assert "id" in d
        assert "state" in d
        assert "our_name" in d
        assert "their_name" in d
        assert "messages" in d
        assert d["state"] == "init"
