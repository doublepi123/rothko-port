/*
 * Copyright (C) 2026 The LineageOS Project
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#define LOG_TAG "UdfpsHandler.rothko"

#include <aidl/android/hardware/biometrics/fingerprint/BnFingerprint.h>
#include <android-base/logging.h>
#include <android-base/unique_fd.h>
#include <android/binder_ibinder.h>
#include <android/binder_manager.h>
#include <android/binder_parcel.h>
#include <android/binder_status.h>

#include <fcntl.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include <chrono>
#include <cstring>
#include <mutex>
#include <thread>

#include "UdfpsHandler.h"
#include "RothkoUdfpsState.h"

#ifndef IMPL_V2
#error "The rothko handler requires the same Xiaomi V2 device ABI as its service"
#endif

using ::aidl::android::hardware::biometrics::fingerprint::AcquiredInfo;

namespace {

constexpr int32_t kCmdFodPressStatus = 1;
constexpr int32_t kCmdFodPressX = 2;
constexpr int32_t kCmdFodPressY = 3;
constexpr int32_t kCmdNit = 10;
constexpr int32_t kNitOff = 0;
constexpr int32_t kNit1000 = 1;
constexpr int32_t kNit110 = 6;

constexpr const char* kDispFeaturePath = "/dev/mi_display/disp_feature";
constexpr const char* kFodPressStatusPath = "/sys/class/touch/touch_dev/fod_press_status";
constexpr unsigned long kIoctlRegisterEvent = 0x400c4407;
constexpr unsigned long kIoctlSetLocalHbm = 0x400c440e;
constexpr uint32_t kEventDisplay = 2;
constexpr uint32_t kLocalHbmOff = 0;
constexpr uint32_t kLocalHbmOn = 2;

constexpr const char* kTouchFeatureService = "vendor.xiaomi.hw.touchfeature.ITouchFeature/default";
constexpr const char* kTouchFeatureDescriptor = "vendor.xiaomi.hw.touchfeature.ITouchFeature";
constexpr transaction_code_t kTouchFeatureSetModeValue = 9;
constexpr int32_t kTouchModeFod = 10;

struct __attribute__((packed)) DispRequest {
    uint64_t base;
    uint32_t value;
};
static_assert(sizeof(DispRequest) == 12);

void* tfCreate(void*) {
    return nullptr;
}
void tfDestroy(void*) {}
binder_status_t tfTransact(AIBinder*, transaction_code_t, const AParcel*, AParcel*) {
    return STATUS_UNKNOWN_TRANSACTION;
}

bool setTouchFodMode(int32_t mode) {
    static const AIBinder_Class* clazz =
            AIBinder_Class_define(kTouchFeatureDescriptor, tfCreate, tfDestroy, tfTransact);
    AIBinder* binder = AServiceManager_checkService(kTouchFeatureService);
    if (binder == nullptr) {
        LOG(ERROR) << "touchfeature service unavailable";
        return false;
    }
    bool ok = false;
    AParcel* in = nullptr;
    AParcel* reply = nullptr;
    if (!AIBinder_associateClass(binder, clazz)) {
        LOG(ERROR) << "touchfeature descriptor mismatch";
    } else if (AIBinder_prepareTransaction(binder, &in) == STATUS_OK &&
               AParcel_writeInt32(in, 0) == STATUS_OK &&
               AParcel_writeInt32(in, kTouchModeFod) == STATUS_OK &&
               AParcel_writeInt32(in, mode) == STATUS_OK) {
        binder_status_t rc = AIBinder_transact(binder, kTouchFeatureSetModeValue, &in, &reply, 0);
        AStatus* status = nullptr;
        ok = rc == STATUS_OK && reply != nullptr &&
             AParcel_readStatusHeader(reply, &status) == STATUS_OK && AStatus_isOk(status);
        if (status != nullptr) AStatus_delete(status);
        LOG(INFO) << "touchfeature setModeValue(0, 10, " << mode << ") rc=" << rc << " ok=" << ok;
    }
    if (in != nullptr) AParcel_delete(in);
    if (reply != nullptr) AParcel_delete(reply);
    AIBinder_decStrong(binder);
    return ok;
}

}  // anonymous namespace

class RothkoUdfpsHandler : public UdfpsHandler {
  public:
    void init(fingerprint_device_t* device) {
        android::base::SetLogger(android::base::LogdLogger(android::base::SYSTEM));
        mDevice = device;
        mDispFd = android::base::unique_fd(open(kDispFeaturePath, O_RDWR | O_CLOEXEC));
        if (mDispFd < 0) PLOG(ERROR) << "open " << kDispFeaturePath;
        stopOperation();
        std::thread([this]() { displayEventLoop(); }).detach();
        std::thread([this]() { fodPressStatusLoop(); }).detach();
    }

    void onOperationStarted() override {
        std::lock_guard<std::mutex> lock(mMutex);
        bool pressed = mState.rawPressed();
        android::base::unique_fd fd(open(kFodPressStatusPath, O_RDONLY | O_CLOEXEC));
        char value = 0;
        if (fd >= 0 && pread(fd.get(), &value, 1, 0) == 1) pressed = value == '1';
        stopOperationLocked();
        mState.startOperation(pressed);
        setTouchFodMode(1);
        LOG(INFO) << "operation started; held touch=" << pressed;
        // A real contact may have woken Keyguard before authentication started.
        // Only the active operation may replay it to the legacy HAL.
        if (pressed) fingerDownLocked(0, 0);
    }

    void onFingerDown(uint32_t x, uint32_t y, float, float) {
        LOG(INFO) << __func__;
        std::lock_guard<std::mutex> lock(mMutex);
        fingerDownLocked(x, y);
    }

    void onFingerUp() {
        LOG(INFO) << __func__;
        fingerUp();
    }

    void onAcquired(int32_t result, int32_t vendorCode) {
        LOG(INFO) << __func__ << " result=" << result << " vendorCode=" << vendorCode;
        switch (static_cast<AcquiredInfo>(result)) {
            case AcquiredInfo::GOOD:
            case AcquiredInfo::PARTIAL:
            case AcquiredInfo::INSUFFICIENT:
            case AcquiredInfo::SENSOR_DIRTY:
            case AcquiredInfo::TOO_SLOW:
            case AcquiredInfo::TOO_FAST:
            case AcquiredInfo::TOO_DARK:
            case AcquiredInfo::TOO_BRIGHT:
            case AcquiredInfo::IMMOBILE:
            case AcquiredInfo::LIFT_TOO_SOON:
                fingerUp();
                break;
            default:
                break;
        }
    }

    void onAuthenticationSucceeded() {
        LOG(INFO) << __func__;
        stopOperation();
    }

    void onAuthenticationFailed() {
        LOG(INFO) << __func__;
        fingerUp();
    }

    void cancel() {
        LOG(INFO) << __func__;
        stopOperation();
    }

  private:
    void extCmd(int32_t cmd, int32_t param) {
        int rc = mDevice->extCmd(mDevice, cmd, param);
        LOG(INFO) << "extCmd(" << cmd << ", " << param << ") = " << rc;
    }

    void setLocalHbm(uint32_t value) {
        DispRequest req = {.base = 1, .value = value};
        if (ioctl(mDispFd.get(), kIoctlSetLocalHbm, &req) < 0) {
            PLOG(ERROR) << "set local hbm " << value;
        } else {
            LOG(INFO) << "set local hbm " << value;
        }
    }

    void fingerDownLocked(uint32_t x, uint32_t y) {
        if (!mState.beginContact()) return;
        extCmd(kCmdFodPressX, 0);
        extCmd(kCmdFodPressY, 0);
        setLocalHbm(kLocalHbmOn);
        extCmd(kCmdFodPressStatus, 1);
        if (x != 0 && y != 0) {
            extCmd(kCmdFodPressX, x);
            extCmd(kCmdFodPressY, y);
        }
    }

    void fingerUp() {
        std::lock_guard<std::mutex> lock(mMutex);
        fingerUpLocked();
    }

    void fingerUpLocked() {
        const bool wasDown = mState.endContact();
        // The panel's display event ends NIT capture. Acquired and pointer UP
        // can arrive before that event; preserve the established HAL timing.
        if (!wasDown) return;
        setLocalHbm(kLocalHbmOff);
        extCmd(kCmdFodPressStatus, 0);
        extCmd(kCmdFodPressX, 0);
        extCmd(kCmdFodPressY, 0);
    }

    void stopOperation() {
        std::lock_guard<std::mutex> lock(mMutex);
        stopOperationLocked();
    }

    void stopOperationLocked() {
        const bool wasCapturing = mState.capturing();
        mState.stopOperation();
        setTouchFodMode(0);
        setLocalHbm(kLocalHbmOff);
        extCmd(kCmdFodPressStatus, 0);
        extCmd(kCmdFodPressX, 0);
        extCmd(kCmdFodPressY, 0);
        if (wasCapturing) extCmd(kCmdNit, kNitOff);
        LOG(INFO) << "operation stopped";
    }

    void displayEventLoop() {
        android::base::unique_fd fd(open(kDispFeaturePath, O_RDWR | O_CLOEXEC));
        if (fd < 0) {
            PLOG(ERROR) << "display event open";
            return;
        }
        for (uint64_t cookie : {uint64_t{0}, uint64_t{1} << 32}) {
            DispRequest req = {.base = cookie, .value = kEventDisplay};
            if (ioctl(fd.get(), kIoctlRegisterEvent, &req) < 0) {
                PLOG(ERROR) << "register display event cookie=" << cookie;
            }
        }
        struct pollfd pfd = {.fd = fd.get(), .events = POLLIN | POLLPRI | POLLRDNORM};
        uint8_t buf[1024];
        while (true) {
            int rc = poll(&pfd, 1, -1);
            if (rc < 0) {
                if (errno == EINTR) continue;
                PLOG(ERROR) << "display event poll";
                std::this_thread::sleep_for(std::chrono::seconds(1));
                continue;
            }
            ssize_t n = read(fd.get(), buf, sizeof(buf));
            if (n <= 0) continue;
            for (ssize_t off = 0; off + 16 <= n;) {
                uint32_t type, size, value;
                memcpy(&type, buf + off + 4, 4);
                memcpy(&size, buf + off + 8, 4);
                memcpy(&value, buf + off + 12, 4);
                if (size < 16 || off + size > static_cast<size_t>(n)) break;
                off += size;
                if (type != kEventDisplay) continue;
                bool start = value != 0 && ((value & 3) == 3 || (value & 8) != 0);
                bool low = (value & 4) != 0;
                LOG(INFO) << "display event value=0x" << std::hex << value;
                std::lock_guard<std::mutex> lock(mMutex);
                if (mState.updateCapture(start)) {
                    extCmd(kCmdNit, mState.capturing() ? (low ? kNit110 : kNit1000) : kNitOff);
                }
            }
        }
    }

    void fodPressStatusLoop() {
        android::base::unique_fd fd(open(kFodPressStatusPath, O_RDONLY | O_CLOEXEC));
        if (fd < 0) {
            PLOG(ERROR) << "open " << kFodPressStatusPath;
            return;
        }
        struct pollfd pfd = {.fd = fd.get(), .events = POLLERR | POLLPRI};
        while (true) {
            {
                std::lock_guard<std::mutex> lock(mMutex);
                char c = 0;
                if (pread(fd.get(), &c, 1, 0) == 1) {
                    const bool pressed = c == '1';
                    if (mState.rawPressChanged(pressed)) {
                        LOG(INFO) << "fod_press_status=" << c;
                        if (pressed) {
                            fingerDownLocked(0, 0);
                        } else {
                            fingerUpLocked();
                        }
                    }
                }
            }
            if (poll(&pfd, 1, -1) < 0 && errno != EINTR) {
                PLOG(ERROR) << "fod_press_status poll";
                std::this_thread::sleep_for(std::chrono::seconds(1));
            }
        }
    }

    fingerprint_device_t* mDevice = nullptr;
    android::base::unique_fd mDispFd;
    std::mutex mMutex;
    RothkoUdfpsState mState;
};

static UdfpsHandler* create() {
    return new RothkoUdfpsHandler();
}

static void destroy(UdfpsHandler* handler) {
    delete handler;
}

extern "C" UdfpsHandlerFactory UDFPS_HANDLER_FACTORY = {
        .create = create,
        .destroy = destroy,
};
