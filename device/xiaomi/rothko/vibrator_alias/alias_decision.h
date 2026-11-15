// SPDX-FileCopyrightText: The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
//
// Deterministic decision core for the opaque Binder alias.
//
// This header contains no binder, servicemanager, VINTF or hardware access.
// The thin binder I/O in service.cpp only feeds observations into Policy and
// performs the returned action. This keeps the state machine testable on a
// build host with a plain C++ compiler.
//
// IMPORTANT: this is a *snapshot* decision. checkService() and addService()
// are not atomic, and servicemanager itself overwrites an existing name. The
// policy can only refuse to overwrite from this process; it cannot stop an
// external competitor. No atomicity guarantee is claimed anywhere.

#pragma once

namespace rothko_alias {

// What the alias observed for the /default name before deciding.
enum class Presence {
    kAbsent,                  // checkService() returned null
    kPresentSameIdentity,     // present and two-way AIBinder_lt says same node
    kPresentDifferentIdentity // present and a different node; never overwrite
};

enum class Action {
    kPublish,           // register the *same* backend handle as /default
    kReuseExisting,     // same node is already /default; do not add again
    kAbortUndeclared,   // default or feature is not in the VINTF manifest
    kAbortLinkFailure,  // linkToDeath failed; must not publish
    kAbortConflict,     // /default has a different identity; refuse
    kAbortAddFailure,   // addService failed; no retry
    kExitForRestart,    // backend died; exit self only, let init restart
};

inline const char* ToString(Action action) {
    switch (action) {
        case Action::kPublish:
            return "publish";
        case Action::kReuseExisting:
            return "reuse-existing";
        case Action::kAbortUndeclared:
            return "abort-undeclared";
        case Action::kAbortLinkFailure:
            return "abort-link-failure";
        case Action::kAbortConflict:
            return "abort-conflict";
        case Action::kAbortAddFailure:
            return "abort-add-failure";
        case Action::kExitForRestart:
            return "exit-for-restart";
    }
    return "unknown";
}

class Policy {
  public:
    enum class State {
        kStart,
        kDeclared,
        kLinked,
        kPublished,
        kReused,
        kFailed,
        kExit,
    };

    inline const char* StateName() const {
        switch (state_) {
            case State::kStart:
                return "start";
            case State::kDeclared:
                return "declared";
            case State::kLinked:
                return "linked";
            case State::kPublished:
                return "published";
            case State::kReused:
                return "reused";
            case State::kFailed:
                return "failed";
            case State::kExit:
                return "exit";
        }
        return "unknown";
    }

    // Order of checks is deliberate: declarations -> link -> presence.
    // `presence` is only meaningful when link_ok is true; callers may pass
    // kAbsent as a placeholder otherwise.
    Action BeforePublish(bool default_declared, bool feature_declared, bool link_ok,
                         Presence presence) {
        if (state_ != State::kStart) {
            // Misuse; never publish from an unexpected state.
            state_ = State::kFailed;
            return Action::kAbortUndeclared;
        }
        if (!default_declared || !feature_declared) {
            state_ = State::kFailed;
            return Action::kAbortUndeclared;
        }
        state_ = State::kDeclared;

        if (!link_ok) {
            // Publishing before a successful death link could leave an alias
            // nobody owns. Refuse instead.
            state_ = State::kFailed;
            return Action::kAbortLinkFailure;
        }
        state_ = State::kLinked;

        switch (presence) {
            case Presence::kPresentSameIdentity:
                state_ = State::kReused;
                return Action::kReuseExisting;
            case Presence::kPresentDifferentIdentity:
                state_ = State::kFailed;
                return Action::kAbortConflict;
            case Presence::kAbsent:
                add_attempted_ = true;
                return Action::kPublish;
        }
        state_ = State::kFailed;
        return Action::kAbortConflict;
    }

    // Only valid after BeforePublish() returned kPublish. Returns true iff the
    // add was reported OK. There is no retry.
    bool AfterAdd(bool add_ok) {
        if (state_ != State::kLinked || !add_attempted_) {
            state_ = State::kFailed;
            return false;
        }
        if (!add_ok) {
            state_ = State::kFailed;
            return false;
        }
        state_ = State::kPublished;
        return true;
    }

    // The backend binder died. The alias only exits itself. It never replays a
    // haptic request, never kills the backend and never swaps an in-flight
    // registration; init restarts this process.
    Action OnBackendDied() {
        state_ = State::kExit;
        return Action::kExitForRestart;
    }

    State state() const { return state_; }
    bool add_attempted() const { return add_attempted_; }

  private:
    State state_ = State::kStart;
    bool add_attempted_ = false;
};

}  // namespace rothko_alias
