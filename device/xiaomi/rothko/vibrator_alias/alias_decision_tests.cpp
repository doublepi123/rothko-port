// SPDX-FileCopyrightText: The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
//
// Host-only tests for the pure decision core (alias_decision.h).
//
// These tests contain no binder, servicemanager, VINTF, Android or hardware
// code. They are compiled and run with the host C++ compiler only. They do NOT
// prove that a Binder registration works; that needs a real Android target
// test later (main's phase).

#include "alias_decision.h"

#include <cstdio>
#include <string>

namespace {

using rothko_alias::Action;
using rothko_alias::Policy;
using rothko_alias::Presence;

int gFailures = 0;

#define EXPECT(cond)                                                       \
    do {                                                                   \
        if (!(cond)) {                                                     \
            std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__,   \
                         #cond);                                           \
            ++gFailures;                                                   \
        }                                                                  \
    } while (0)

void TestAbsentPublishesThenSucceeds() {
    Policy p;
    EXPECT(p.BeforePublish(true, true, true, Presence::kAbsent) == Action::kPublish);
    EXPECT(p.add_attempted());
    EXPECT(p.AfterAdd(true));
    EXPECT(p.state() == Policy::State::kPublished);
}

void TestAddFailureStopsWithoutRetry() {
    Policy p;
    EXPECT(p.BeforePublish(true, true, true, Presence::kAbsent) == Action::kPublish);
    EXPECT(!p.AfterAdd(false));
    EXPECT(p.state() == Policy::State::kFailed);
    EXPECT(p.add_attempted());
}

void TestSameIdentityReusesExisting() {
    Policy p;
    EXPECT(p.BeforePublish(true, true, true, Presence::kPresentSameIdentity) ==
           Action::kReuseExisting);
    EXPECT(!p.add_attempted());
    EXPECT(p.state() == Policy::State::kReused);
}

void TestDifferentIdentityConflicts() {
    Policy p;
    EXPECT(p.BeforePublish(true, true, true, Presence::kPresentDifferentIdentity) ==
           Action::kAbortConflict);
    EXPECT(!p.add_attempted());
    EXPECT(p.state() == Policy::State::kFailed);
}

void TestLinkFailureNeverPublishes() {
    Policy p;
    EXPECT(p.BeforePublish(true, true, false, Presence::kAbsent) ==
           Action::kAbortLinkFailure);
    EXPECT(!p.add_attempted());
    EXPECT(p.state() == Policy::State::kFailed);
}

void TestLinkFailureWinsOverPresence() {
    // Even if /default already looks like the same node, publish/reuse is only
    // considered after a successful death link.
    Policy p;
    EXPECT(p.BeforePublish(true, true, false, Presence::kPresentSameIdentity) ==
           Action::kAbortLinkFailure);
    EXPECT(!p.add_attempted());
    EXPECT(p.state() == Policy::State::kFailed);
}

void TestUndeclaredAbortsBeforeLinkOrPresence() {
    {
        Policy p;
        EXPECT(p.BeforePublish(false, true, true, Presence::kAbsent) ==
               Action::kAbortUndeclared);
        EXPECT(!p.add_attempted());
        EXPECT(p.state() == Policy::State::kFailed);
    }
    {
        Policy p;
        EXPECT(p.BeforePublish(true, false, true, Presence::kAbsent) ==
               Action::kAbortUndeclared);
        EXPECT(!p.add_attempted());
    }
    {
        // Undeclared wins even if link "succeeded" is reported.
        Policy p;
        EXPECT(p.BeforePublish(false, false, true, Presence::kAbsent) ==
               Action::kAbortUndeclared);
    }
    {
        // Undeclared wins over a failed link as well; the reason is explicit.
        Policy p;
        EXPECT(p.BeforePublish(false, true, false, Presence::kAbsent) ==
               Action::kAbortUndeclared);
        EXPECT(!p.add_attempted());
    }
}

void TestBackendDeathOnlyExits() {
    Policy published;
    EXPECT(published.BeforePublish(true, true, true, Presence::kAbsent) == Action::kPublish);
    EXPECT(published.AfterAdd(true));
    EXPECT(published.OnBackendDied() == Action::kExitForRestart);
    EXPECT(published.state() == Policy::State::kExit);

    Policy reused;
    EXPECT(reused.BeforePublish(true, true, true, Presence::kPresentSameIdentity) ==
           Action::kReuseExisting);
    EXPECT(reused.OnBackendDied() == Action::kExitForRestart);
    EXPECT(reused.state() == Policy::State::kExit);
    EXPECT(!reused.add_attempted());
}

void TestRegistrarRestartReusesSameNode() {
    // First alias process published nothing new: it observed the same node
    // already registered by a previous registrar.
    Policy restarted;
    EXPECT(restarted.BeforePublish(true, true, true, Presence::kPresentSameIdentity) ==
           Action::kReuseExisting);
    EXPECT(!restarted.add_attempted());
    EXPECT(restarted.state() == Policy::State::kReused);
}

void TestFeatureRestartPublishesNewNode() {
    // After the backend died, the old /default node is gone; the restarted
    // alias sees the new feature node and must publish it.
    Policy afterRestart;
    EXPECT(afterRestart.BeforePublish(true, true, true, Presence::kAbsent) == Action::kPublish);
    EXPECT(afterRestart.AfterAdd(true));
    EXPECT(afterRestart.state() == Policy::State::kPublished);
}

void TestAfterAddRequiresPublishPath() {
    Policy p;
    EXPECT(!p.AfterAdd(true));
    EXPECT(p.state() == Policy::State::kFailed);
}

void TestActionNamesAreStable() {
    EXPECT(std::string(rothko_alias::ToString(Action::kPublish)) == "publish");
    EXPECT(std::string(rothko_alias::ToString(Action::kReuseExisting)) == "reuse-existing");
    EXPECT(std::string(rothko_alias::ToString(Action::kExitForRestart)) == "exit-for-restart");
}

}  // namespace

int main() {
    TestAbsentPublishesThenSucceeds();
    TestAddFailureStopsWithoutRetry();
    TestSameIdentityReusesExisting();
    TestDifferentIdentityConflicts();
    TestLinkFailureNeverPublishes();
    TestLinkFailureWinsOverPresence();
    TestUndeclaredAbortsBeforeLinkOrPresence();
    TestBackendDeathOnlyExits();
    TestRegistrarRestartReusesSameNode();
    TestFeatureRestartPublishesNewNode();
    TestAfterAddRequiresPublishPath();
    TestActionNamesAreStable();

    if (gFailures != 0) {
        std::fprintf(stderr, "%d decision-core test(s) failed\n", gFailures);
        return 1;
    }
    std::puts("all decision-core tests passed (host C++ only; not a Binder test)");
    return 0;
}
