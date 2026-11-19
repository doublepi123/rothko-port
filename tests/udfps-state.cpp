/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
#include "../device/xiaomi/rothko/udfps/RothkoUdfpsState.h"
#include <cassert>
#include <iostream>

int main() {
    {
        RothkoUdfpsState idle;
        assert(idle.rawPressChanged(true));
        assert(!idle.beginContact());
        assert(!idle.updateCapture(true));
        assert(!idle.capturing());
    }
    // Panel and framework events use independent queues. Either order must
    // capture; acquired/UP must not shorten the panel's NIT capture window.
    for (bool displayFirst : {false, true}) {
        RothkoUdfpsState request;
        request.startOperation(false);
        if (displayFirst) assert(request.updateCapture(true));
        assert(request.beginContact());
        assert(!request.beginContact());
        if (!displayFirst) assert(request.updateCapture(true));
        assert(request.capturing());
        assert(!request.updateCapture(true));
        assert(request.endContact());
        assert(request.capturing());
        assert(request.updateCapture(false));
        assert(!request.capturing());
        assert(request.operationActive());
        assert(request.beginContact());
        assert(request.updateCapture(true));
        request.stopOperation();
        assert(!request.capturing());
    }
    {
        // A contact can wake Keyguard before its authentication request starts.
        RothkoUdfpsState held;
        held.rawPressChanged(true);
        assert(!held.beginContact());
        held.startOperation(true);
        assert(!held.rawPressChanged(true));
        assert(held.beginContact());
        assert(held.updateCapture(true));
        held.stopOperation();
        assert(!held.beginContact());
        assert(!held.updateCapture(true));
        held.startOperation(true);
        assert(held.beginContact());
    }
    // Success, cancellation, error and close retire the operation. Late
    // physical/display events must never revive it without a new request.
    for (int terminal = 0; terminal != 4; ++terminal) {
        RothkoUdfpsState done;
        done.startOperation(false);
        assert(done.beginContact());
        assert(done.updateCapture(true));
        done.stopOperation();
        assert(!done.operationActive());
        for (int retry = 0; retry != 1000; ++retry) {
            done.rawPressChanged(true);
            assert(!done.beginContact());
            assert(!done.updateCapture(true));
            done.rawPressChanged(false);
            done.endContact();
            assert(!done.capturing());
        }
    }
    std::cout << "PASS: idle gate, both display/pointer orders, acquired before display end, "
                 "active retry, held wake contact, and terminal late events\n";
}
