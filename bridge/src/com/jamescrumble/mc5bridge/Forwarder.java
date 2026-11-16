package com.jamescrumble.mc5bridge;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.ArrayList;
import java.util.List;

/**
 * "Server at address" (documentation/architecture.md): the game always talks to 127.0.0.1; these listeners on the game's ports pass every TCP connection on to the
 * chosen host (same port numbers). So nothing in the game depends on the mode.
 */
final class Forwarder {
    /** HTTP, HTTPS (also chat), alert, game server (AH) and its two controller ports. */
    static final int[] PORTS = {18080, 18443, 33508, 33600, 33601, 33602};

    private final String host;
    private final List<ServerSocket> servers = new ArrayList<>();
    private volatile boolean stopped;

    Forwarder(String host) { this.host = host; }

    /** Opens the listeners; returns the ports that could not be bound (another process holds them). */
    List<Integer> start() {
        List<Integer> failed = new ArrayList<>();
        for (int port : PORTS) {
            try {
                ServerSocket ss = new ServerSocket();
                ss.setReuseAddress(true);
                ss.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), port));
                servers.add(ss);
                Thread t = new Thread(() -> accept(ss, port), "fwd-" + port);
                t.setDaemon(true);
                t.start();
            } catch (IOException e) {
                failed.add(port);
            }
        }
        return failed;
    }

    void stop() {
        stopped = true;
        for (ServerSocket s : servers) try { s.close(); } catch (IOException ignored) { }
        servers.clear();
    }

    private void accept(ServerSocket ss, int port) {
        while (!stopped) {
            try {
                Socket in = ss.accept();
                Thread t = new Thread(() -> pipe(in, port), "fwd-conn-" + port);
                t.setDaemon(true);
                t.start();
            } catch (IOException e) {
                return;
            }
        }
    }

    private void pipe(Socket in, int port) {
        Socket out = new Socket();
        try {
            out.connect(new InetSocketAddress(host, port), 5000);
            in.setTcpNoDelay(true);
            out.setTcpNoDelay(true);
        } catch (IOException e) {
            close(in);
            close(out);
            return;
        }
        Thread back = new Thread(() -> copy(out, in), "fwd-back");
        back.setDaemon(true);
        back.start();
        copy(in, out);
    }

    private static void copy(Socket from, Socket to) {
        byte[] buf = new byte[16384];
        try {
            InputStream i = from.getInputStream();
            OutputStream o = to.getOutputStream();
            int n;
            while ((n = i.read(buf)) >= 0) {
                o.write(buf, 0, n);
                o.flush();
            }
        } catch (IOException ignored) {
        } finally {
            close(from);
            close(to);
        }
    }

    private static void close(Socket s) {
        try { s.close(); } catch (IOException ignored) { }
    }
}
