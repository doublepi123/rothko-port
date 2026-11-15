# ImsService.apk (not included)

`RothkoImsService` (see `../Android.bp`) imports the stock MediaTek/Xiaomi IMS
service. It is proprietary and is not redistributed here.

Extract it from the same stock firmware the port targets
(`OS3.0.308.0.WNNCNXM`, Android 16):

    system_ext/priv-app/ImsService/ImsService.apk
    sha256 a4b25608dfd07d0789f1b24b0d719ac46de233c91765d1d94b890d53294638c3

and place it here as `ImsService.apk`. Soong re-signs it with the platform
certificate (`certificate: "platform"`).

Note: the copy used for the reference build had sha256
32f67e6d9083c8e6f9dd81be8309fd2dc2c96fdf14d2bf8b0274ab9ab2e30114, which differs
from the stock file; the difference has not been re-audited for this export.
