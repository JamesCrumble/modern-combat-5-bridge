package com.jamescrumble.mc5bridge;

import android.app.Activity;
import android.app.Application;
import android.content.Context;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;

import java.lang.ref.WeakReference;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

/**
 * The game's MainActivity runs once per process: its onCreate finishes any later instance that is not the task root while its static
 * self reference (set by the first instance, never cleared) is there, and the game ends its process itself when it quits. In B the
 * process outlives the game (ServerService keeps it), so after the game was closed another way (swiped from recents, destroyed by the
 * system) "Play" only flashed: the new game screen finished itself at once. Hence the bridge watches the game screens of the process:
 * when the last one is gone, the process ends as the game would end it (progress mirrored first), except with "Доступ из локальной
 * сети", where the server keeps serving the other phones and the next "Play" restarts the process ({@link #ended}).
 *
 * A game screen is MainActivity or a subclass of it: on foldables (a hinge angle sensor) and the Surface Duo, MainActivity finishes
 * itself in onCreate and starts MainActivityMSDuo, which is then the game. So a screen being destroyed only ends the game when, after
 * a short wait ({@link #SETTLE_MS}), no game screen is left: the hand-over, a configuration change or a later instance finishing itself
 * leave one.
 *
 * All of it runs on the main thread (lifecycle callbacks and the bridge screen).
 */
final class GameWatch implements Application.ActivityLifecycleCallbacks {
    private static final long SETTLE_MS = 3000;
    private static boolean installed;
    private static final List<WeakReference<Activity>> screens = new ArrayList<>();   // game screens created and not destroyed
    private static boolean started;                                                    // a game screen was created in this process
    private static volatile boolean ended;   // the game was closed: it cannot start again in this process
    private final Context app;
    private final Handler main = new Handler(Looper.getMainLooper());

    private GameWatch(Context app) { this.app = app; }

    static synchronized void install(Context c) {
        if (installed) return;
        Application a = (Application) c.getApplicationContext();
        a.registerActivityLifecycleCallbacks(new GameWatch(a));
        installed = true;
    }

    /** The live game screen (the newest one that is not finishing), or null. */
    static Activity screen() {
        for (int i = screens.size() - 1; i >= 0; i--) {
            Activity a = screens.get(i).get();
            if (a != null && !a.isFinishing() && !a.isDestroyed()) return a;
        }
        return null;
    }

    /** The game is open in this process (bring {@link #screen} to the front instead of starting another one). */
    static boolean running() { return !ended && screen() != null; }

    /** The game already ran in this process and was closed: it starts again only in a new process. */
    static boolean ended() { return ended || (started && screen() == null); }

    private static boolean isGame(Activity a) {
        String main = Storage.GAME_PACKAGE + ".MainActivity";
        for (Class<?> k = a.getClass(); k != null; k = k.getSuperclass())
            if (k.getName().equals(main)) return true;
        return false;
    }

    @Override public void onActivityCreated(Activity a, Bundle state) {
        if (!isGame(a)) return;
        screens.add(new WeakReference<>(a));
        String name = a.getClass().getSimpleName();
        if (!started) {
            started = true;
            BridgeLog.i(app, "Игра запущена" + (name.equals("MainActivity") ? "" : " (" + name + ")"));
        } else {
            BridgeLog.i(app, "Экран игры: " + name);
        }
    }

    @Override public void onActivityDestroyed(Activity a) {
        if (!isGame(a)) return;
        for (Iterator<WeakReference<Activity>> it = screens.iterator(); it.hasNext(); ) {
            Activity s = it.next().get();
            if (s == null || s == a) it.remove();
        }
        if (a.isChangingConfigurations()) return;   // recreated at once
        main.postDelayed(this::check, SETTLE_MS);
    }

    /** After a game screen was destroyed: the game ended if no game screen is left. */
    private void check() {
        if (ended || screen() != null) return;
        ended = true;
        if (Settings.load(app).on(Settings.SERVER_LAN)) {
            BridgeLog.i(app, "Игра закрыта; процесс остаётся: сервер нужен локальной сети");
            return;
        }
        BridgeLog.i(app, "Игра закрыта: процесс завершается, как это делает сама игра");
        Backend.flushMirror(app);
        android.os.Process.killProcess(android.os.Process.myPid());
    }

    @Override public void onActivityStarted(Activity a) { }
    @Override public void onActivityResumed(Activity a) { }
    @Override public void onActivityPaused(Activity a) { }
    @Override public void onActivityStopped(Activity a) { }
    @Override public void onActivitySaveInstanceState(Activity a, Bundle out) { }
}
