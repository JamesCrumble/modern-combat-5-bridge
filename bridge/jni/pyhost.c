/* Embeds CPython (official python-3.14 Android build) in the bridge process (documentation/architecture.md).
 * Java: PyHost.run(home, argv) blocks until Py_RunMain returns (the server script runs as __main__); PyHost.redirectStdio() sends the
 * native stdout/stderr to logcat (Python's own sys.stdout/sys.stderr already go to logcat). Based on CPython's Android/testbed main_activity.c. */
#include <android/log.h>
#include <errno.h>
#include <jni.h>
#include <limits.h>
#include <pthread.h>
#include <Python.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#define TAG "mc5py"

typedef struct { FILE *file; int fd; int prio; const char *tag; int pipe[2]; } Stream;
static Stream STREAMS[] = {
    {NULL, STDOUT_FILENO, ANDROID_LOG_INFO, "py.stdout", {-1, -1}},
    {NULL, STDERR_FILENO, ANDROID_LOG_WARN, "py.stderr", {-1, -1}},
    {NULL, -1, 0, NULL, {-1, -1}},
};

static void *pump(void *arg) {
    Stream *s = arg;
    char buf[4000];
    ssize_t n;
    while ((n = read(s->pipe[0], buf, sizeof buf - 1)) > 0) {
        buf[n] = 0;
        __android_log_write(s->prio, s->tag, buf);
    }
    return NULL;
}

JNIEXPORT void JNICALL Java_com_jamescrumble_mc5bridge_PyHost_redirectStdio(JNIEnv *env, jclass cls) {
    STREAMS[0].file = stdout;
    STREAMS[1].file = stderr;
    for (Stream *s = STREAMS; s->file; s++) {
        setvbuf(s->file, 0, _IONBF, 0);
        if (pipe(s->pipe) || dup2(s->pipe[1], s->fd) == -1) return;
        pthread_t t;
        if (pthread_create(&t, 0, pump, s) == 0) pthread_detach(t);
    }
}

JNIEXPORT jint JNICALL Java_com_jamescrumble_mc5bridge_PyHost_run(JNIEnv *env, jclass cls, jstring home, jobjectArray args) {
    const char *home_utf8 = (*env)->GetStringUTFChars(env, home, NULL);
    sigset_t set;                       /* SIGUSR1 is blocked in an Android app (Signal Catcher); Python expects it free */
    sigemptyset(&set);
    sigaddset(&set, SIGUSR1);
    pthread_sigmask(SIG_UNBLOCK, &set, NULL);

    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    config.install_signal_handlers = 0; /* not the main thread of the process */
    jsize argc = (*env)->GetArrayLength(env, args);
    const char *argv[argc + 1];
    for (int i = 0; i < argc; i++) {
        jobject a = (*env)->GetObjectArrayElement(env, args, i);
        argv[i] = (*env)->GetStringUTFChars(env, (jstring)a, NULL);
    }
    argv[argc] = NULL;
    PyStatus st = PyConfig_SetBytesArgv(&config, argc, (char **)argv);
    if (!PyStatus_Exception(st)) st = PyConfig_SetBytesString(&config, &config.home, home_utf8);
    if (!PyStatus_Exception(st)) st = Py_InitializeFromConfig(&config);
    if (PyStatus_Exception(st)) {
        __android_log_print(ANDROID_LOG_ERROR, TAG, "Python init failed: %s", st.err_msg ? st.err_msg : "?");
        return 1;
    }
    return Py_RunMain();
}
