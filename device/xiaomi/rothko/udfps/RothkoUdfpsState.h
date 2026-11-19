/*
 * Copyright (C) 2026 The LineageOS Project
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

// All access is serialized by RothkoUdfpsHandler's mutex, including the actual
// hardware writes. A cached touch or late display event cannot open an idle
// sensor. During an authorized operation, display capture follows the panel
// protocol independently of the ordering of pointer and acquired callbacks.
class RothkoUdfpsState {
  public:
    void startOperation(bool pressed) {
        mOperationActive = true;
        mRawPressed = pressed;
        mFingerDown = false;
        mCapturing = false;
    }

    void stopOperation() {
        mOperationActive = false;
        mFingerDown = false;
        mCapturing = false;
    }

    bool rawPressChanged(bool pressed) {
        if (pressed == mRawPressed) return false;
        mRawPressed = pressed;
        return true;
    }

    bool beginContact() {
        if (!mOperationActive || mFingerDown) return false;
        mFingerDown = true;
        return true;
    }

    bool endContact() {
        const bool wasDown = mFingerDown;
        mFingerDown = false;
        return wasDown;
    }

    bool updateCapture(bool requested) {
        const bool capture = requested && mOperationActive;
        if (capture == mCapturing) return false;
        mCapturing = capture;
        return true;
    }

    bool operationActive() const { return mOperationActive; }
    bool rawPressed() const { return mRawPressed; }
    bool capturing() const { return mCapturing; }

  private:
    bool mOperationActive = false;
    bool mRawPressed = false;
    bool mFingerDown = false;
    bool mCapturing = false;
};
