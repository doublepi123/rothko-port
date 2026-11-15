// SPDX-FileCopyrightText: The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
//
// Registration-only opaque Binder alias for the Rothko vibrator HAL.
//
// The stock ODM service registers only
//   android.hardware.vibrator.IVibrator/vibratorfeature
// while the framework asks for
//   android.hardware.vibrator.IVibrator/default
//
// This process never implements, wraps or calls the vibrator HAL. It obtains
// the *remote* binder of the real feature service and registers that same
// handle under /default. The binder node stays owned by the stock HAL process;
// this process is only the registrar. Consequently:
//   - no HAL transaction (typed or untyped) is made by this process;
//   - no local HAL/forward object is created;
//   - the node's VINTF stability is unchanged.
//
// The only binder operations here are servicemanager lookups/add (SELinux
// service_manager add/find, already granted to hal_vibrator_server) and a
// driver-level death notification on the remote node.
//
// Ordering is deliberate:
//   thread pool -> declarations -> waitForService -> linkToDeath -> check -> add
//
// checkService() and addService() are NOT atomic. servicemanager itself
// overwrites an existing name. This process refuses to overwrite a different
// identity, but that is a best-effort policy, not a race guarantee. The
// integration precondition is that this alias is the only publisher of
// /default; that must be reviewed at build/integration time.

#include <android-base/logging.h>
#include <android/binder_auto_utils.h>
#include <android/binder_ibinder.h>
#include <android/binder_manager.h>
#include <android/binder_process.h>
#include <android/binder_status.h>

#include <cstdlib>
#include <string>
#include <unistd.h>

#include "alias_decision.h"

namespace {

using rothko_alias::Action;
using rothko_alias::Policy;
using rothko_alias::Presence;

constexpr char kFeatureInstance[] = "android.hardware.vibrator.IVibrator/vibratorfeature";
constexpr char kDefaultInstance[] = "android.hardware.vibrator.IVibrator/default";

// Kept alive for the process lifetime; binder does not own it.
AIBinder_DeathRecipient* gBackendDeathRecipient = nullptr;

void OnBackendDied(void* /*cookie*/) {
    // Only exit this alias. init restarts it, which reconnects to the current
    // feature node and republishes /default. Never replay a haptic request,
    // never kill or restart the stock HAL, never touch hardware from here.
    LOG(ERROR) << "opaque backend " << kFeatureInstance
               << " died; exiting alias so init can restart it";
    _exit(EXIT_FAILURE);
}

// Two-way AIBinder_lt is the documented identity test for binders: neither
// side is less than the other. It is a local comparison, not a transaction.
bool SameIdentity(AIBinder* a, AIBinder* b) {
    if (a == nullptr || b == nullptr) return false;
    return !AIBinder_lt(a, b) && !AIBinder_lt(b, a);
}

int Fail(const std::string& reason) {
    LOG(ERROR) << "vibrator alias not publishing " << kDefaultInstance << ": " << reason;
    return EXIT_FAILURE;
}

}  // namespace

int main() {
    // The thread pool must really be started before waitForService() or
    // linkToDeath(); both may need incoming calls/callbacks.
    ABinderProcess_setThreadPoolMaxThreadCount(4);
    ABinderProcess_startThreadPool();

    const bool defaultDeclared = AServiceManager_isDeclared(kDefaultInstance);
    const bool featureDeclared = AServiceManager_isDeclared(kFeatureInstance);

    bool linkOk = false;
    std::string linkFailureReason = "linkToDeath not attempted";
    ndk::SpAIBinder backend;

    if (defaultDeclared && featureDeclared) {
        AIBinder* rawBackend = AServiceManager_waitForService(kFeatureInstance);
        if (rawBackend == nullptr) {
            linkFailureReason = "waitForService returned null";
        } else {
            backend.set(rawBackend);  // adopts the returned strong reference
            gBackendDeathRecipient = AIBinder_DeathRecipient_new(OnBackendDied);
            if (gBackendDeathRecipient == nullptr) {
                linkFailureReason = "AIBinder_DeathRecipient_new failed";
            } else {
                // Link before any check/add. Publishing an alias whose death
                // link failed could leave a stale registration.
                const binder_status_t linkStatus =
                        AIBinder_linkToDeath(backend.get(), gBackendDeathRecipient, nullptr);
                if (linkStatus == STATUS_OK) {
                    linkOk = true;
                } else {
                    linkFailureReason =
                            "AIBinder_linkToDeath failed: " + std::to_string(linkStatus);
                }
            }
        }
    }

    // Only check /default after the death link succeeded. checkService() is a
    // snapshot and is explicitly not atomic with addService().
    AIBinder* rawExisting = linkOk ? AServiceManager_checkService(kDefaultInstance) : nullptr;
    ndk::SpAIBinder existing(rawExisting);

    Presence presence = Presence::kAbsent;
    if (rawExisting != nullptr) {
        presence = SameIdentity(backend.get(), existing.get())
                           ? Presence::kPresentSameIdentity
                           : Presence::kPresentDifferentIdentity;
    }

    Policy policy;
    const Action action =
            policy.BeforePublish(defaultDeclared, featureDeclared, linkOk, presence);

    auto unlinkAndFail = [&](const std::string& reason) {
        // Safe cleanup on the error path: drop the death link, then exit. The
        // process exit releases the service reference; no hardware calls.
        if (linkOk) {
            AIBinder_unlinkToDeath(backend.get(), gBackendDeathRecipient, nullptr);
        }
        return Fail(reason);
    };

    switch (action) {
        case Action::kPublish: {
            // Register the SAME opaque remote handle. Do not create a local
            // binder object and do not change its class/stability.
            const binder_status_t addStatus =
                    AServiceManager_addService(backend.get(), kDefaultInstance);
            if (!policy.AfterAdd(addStatus == STATUS_OK)) {
                return unlinkAndFail("addService failed: " + std::to_string(addStatus));
            }
            LOG(INFO) << "vibrator alias registered " << kDefaultInstance
                      << " as the opaque node of " << kFeatureInstance;
            break;
        }
        case Action::kReuseExisting:
            // A previous registrar already published this same node (for
            // example after this process restarted). Do not add again; stay
            // alive so the death link still makes us exit on backend death.
            LOG(INFO) << "vibrator alias found " << kDefaultInstance
                      << " with the same binder identity; not adding again";
            break;
        case Action::kAbortUndeclared:
            return Fail("default or feature instance is not declared in VINTF");
        case Action::kAbortLinkFailure:
            return Fail(linkFailureReason);
        case Action::kAbortConflict:
            return unlinkAndFail(
                    "existing /default has a different binder identity; refusing to overwrite");
        case Action::kAbortAddFailure:
            return unlinkAndFail("addService path rejected");
        case Action::kExitForRestart:
            _exit(EXIT_FAILURE);
    }

    ABinderProcess_joinThreadPool();
    return EXIT_FAILURE;  // joinThreadPool does not return
}
