// SPDX-License-Identifier: Apache-2.0

#include <cstddef>
#include <cstdint>
#include <string>

#if !defined(__aarch64__)
#error The stock Rothko VT libraries use the 64-bit Arm ABI.
#endif

// Both references and the receiver are passed as addresses. Keep the stock
// constructor entry point local to the VT audio sink's dependencies. The
// Android 17 constructor adds codecProvenance; use its documented empty default.
#define VT_AUDIO_TRACK_CONSTRUCTOR \
    "_ZN7android10AudioTrackC1E19audio_stream_type_tj14audio_format_t20audio_channel_mask_tm" \
    "20audio_output_flags_tRKNS_2wpINS0_19IAudioTrackCallbackEEEi15audio_session_t" \
    "NS0_13transfer_typeEPK20audio_offload_info_tRKNS_7content22AttributionSourceState" \
    "EPK18audio_attributes_tbfi"

extern "C" void android17_audio_track_constructor(
    void* receiver, std::int32_t stream_type, std::uint32_t sample_rate,
    std::int32_t format, std::uint32_t channel_mask, std::size_t frame_count,
    std::int32_t output_flags, const void* callback, std::int32_t notification_frames,
    std::int32_t session, std::int32_t transfer, const void* offload,
    const void* attribution, const void* attributes, bool do_not_reconnect,
    float max_required_speed, std::int32_t device, const std::string* codec_provenance)
    asm(VT_AUDIO_TRACK_CONSTRUCTOR "RKNSt3__112basic_stringIcNSM_11char_traitsIcEENSM_9allocatorIcEEEE");

extern "C" __attribute__((visibility("default"))) void stock_audio_track_constructor(
    void* receiver, std::int32_t stream_type, std::uint32_t sample_rate,
    std::int32_t format, std::uint32_t channel_mask, std::size_t frame_count,
    std::int32_t output_flags, const void* callback, std::int32_t notification_frames,
    std::int32_t session, std::int32_t transfer, const void* offload,
    const void* attribution, const void* attributes, bool do_not_reconnect,
    float max_required_speed, std::int32_t device) asm(VT_AUDIO_TRACK_CONSTRUCTOR);

void stock_audio_track_constructor(
    void* receiver, std::int32_t stream_type, std::uint32_t sample_rate,
    std::int32_t format, std::uint32_t channel_mask, std::size_t frame_count,
    std::int32_t output_flags, const void* callback, std::int32_t notification_frames,
    std::int32_t session, std::int32_t transfer, const void* offload,
    const void* attribution, const void* attributes, bool do_not_reconnect,
    float max_required_speed, std::int32_t device) {
    const std::string codec_provenance;
    android17_audio_track_constructor(
        receiver, stream_type, sample_rate, format, channel_mask, frame_count,
        output_flags, callback, notification_frames, session, transfer, offload,
        attribution, attributes, do_not_reconnect, max_required_speed, device,
        &codec_provenance);
}
