// SPDX-License-Identifier: GPL-3.0-or-later
// Included in the Aster build of the OpenSL guest bridge, after its HAL callback.
// The Android queue resets its playback index to zero on Clear. A delayed HAL
// notification must refer to a completed buffer in the current queue before
// it can call back into the game. Access is serialized by g_audioMutex.
static SLuint32 g_deliveredAudioIndex = 0;

static SLresult registerAsterAudioCallback(uint32_t callback, uint32_t context) {
    std::lock_guard<std::mutex> lock(g_audioMutex);
    if (!g_hostPlayerBufferQueue) return SL_RESULT_PRECONDITIONS_VIOLATED;
    SLAndroidSimpleBufferQueueState state{};
    SLresult rc = (*g_hostPlayerBufferQueue)->GetState(g_hostPlayerBufferQueue, &state);
    if (rc != SL_RESULT_SUCCESS) return rc;
    g_deliveredAudioIndex = state.index;
    g_guestCallbackAddr = callback;
    g_guestCallbackContext = context;
    return SL_RESULT_SUCCESS;
}

static SLresult clearAsterAudioQueue() {
    std::lock_guard<std::mutex> lock(g_audioMutex);
    if (!g_hostPlayerBufferQueue) return SL_RESULT_PRECONDITIONS_VIOLATED;
    SLresult rc = (*g_hostPlayerBufferQueue)->Clear(g_hostPlayerBufferQueue);
    if (rc == SL_RESULT_SUCCESS) {
        g_deliveredAudioIndex = 0;
        g_currentBufferIndex = 0;
    }
    return rc;
}

static void closeAsterAudioPlayer() {
    std::lock_guard<std::mutex> lock(g_audioMutex);
    if (!g_hostPlayerObject) return;
    (*g_hostPlayerObject)->Destroy(g_hostPlayerObject);
    g_hostPlayerObject = nullptr;
    g_hostPlayerPlay = nullptr;
    g_hostPlayerBufferQueue = nullptr;
    g_hostPlayerVolume = nullptr;
    g_guestCallbackAddr = 0;
    g_guestCallbackContext = 0;
    g_deliveredAudioIndex = 0;
    g_currentBufferIndex = 0;
}

static SLresult openAsterAudioPlayer(SLDataSource* source, SLDataSink* sink) {
    std::lock_guard<std::mutex> lock(g_audioMutex);
    if (g_hostPlayerBufferQueue) return SL_RESULT_SUCCESS;
    if (!g_hostEngineEngine || !g_hostOutputMixObject) return SL_RESULT_PRECONDITIONS_VIOLATED;

    const SLInterfaceID ids[] = {SL_IID_ANDROIDSIMPLEBUFFERQUEUE, SL_IID_VOLUME,
                                 SL_IID_ANDROIDCONFIGURATION};
    const SLboolean required[] = {SL_BOOLEAN_TRUE, SL_BOOLEAN_FALSE, SL_BOOLEAN_FALSE};
    SLObjectItf player = nullptr;
    SLPlayItf play = nullptr;
    SLAndroidSimpleBufferQueueItf queue = nullptr;
    SLVolumeItf volume = nullptr;
    SLresult rc = (*g_hostEngineEngine)->CreateAudioPlayer(
        g_hostEngineEngine, &player, source, sink, 3, ids, required);
    if (rc == SL_RESULT_SUCCESS) {
        SLAndroidConfigurationItf config = nullptr;
        if ((*player)->GetInterface(player, SL_IID_ANDROIDCONFIGURATION, &config) == SL_RESULT_SUCCESS) {
            SLint32 stream = SL_ANDROID_STREAM_MEDIA;
            (*config)->SetConfiguration(config, SL_ANDROID_KEY_STREAM_TYPE, &stream, sizeof(stream));
        }
        rc = (*player)->Realize(player, SL_BOOLEAN_FALSE);
    }
    if (rc == SL_RESULT_SUCCESS) rc = (*player)->GetInterface(player, SL_IID_PLAY, &play);
    if (rc == SL_RESULT_SUCCESS) rc = (*player)->GetInterface(player, SL_IID_ANDROIDSIMPLEBUFFERQUEUE, &queue);
    if (rc == SL_RESULT_SUCCESS) rc = (*queue)->RegisterCallback(queue, HostBqPlayerCallback, nullptr);
    if (rc != SL_RESULT_SUCCESS) {
        if (player) (*player)->Destroy(player);
        __android_log_print(ANDROID_LOG_WARN, "AsterAudio", "OpenSL player setup failed (%u)", rc);
        return rc;
    }
    if ((*player)->GetInterface(player, SL_IID_VOLUME, &volume) == SL_RESULT_SUCCESS)
        (*volume)->SetVolumeLevel(volume, 0);
    g_hostPlayerObject = player;
    g_hostPlayerPlay = play;
    g_hostPlayerVolume = volume;
    g_hostPlayerBufferQueue = queue;
    return SL_RESULT_SUCCESS;
}
