package com.popcap.SexyAppFramework;

/** Iris I40's bounded background handshake, adapted to Aster's retained DEX. */
public final class AsterBackgroundFrames {
    private AsterBackgroundFrames() {}

    public static void awaitFrame(AndroidSurfaceView view) {
        Object signal = new Object();
        synchronized (signal) {
            if (!view.mbDrawingFrames) return;
            view.mbNotifyOnDrawEventObject = signal;
            view.requestRender();
            long end = android.os.SystemClock.uptimeMillis() + 250;
            try {
                while (view.mbNotifyOnDrawEventObject == signal) {
                    long remaining = end - android.os.SystemClock.uptimeMillis();
                    if (remaining <= 0) break;
                    signal.wait(remaining);
                }
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
            } finally {
                if (view.mbNotifyOnDrawEventObject == signal) view.mbNotifyOnDrawEventObject = null;
                view.mbDrawingFrames = false;
            }
        }
    }

    public static boolean acknowledgeFrame(AndroidSurfaceView view) {
        Object signal = view.mbNotifyOnDrawEventObject;
        if (signal == null) return false;
        synchronized (signal) {
            if (view.mbNotifyOnDrawEventObject == signal) {
                view.mbNotifyOnDrawEventObject = null;
                signal.notifyAll();
            }
        }
        return true;
    }
}
