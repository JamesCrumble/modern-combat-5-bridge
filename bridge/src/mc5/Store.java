package mc5;

import android.os.Bundle;
import android.util.Log;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Local replacement of Google Play Billing for the Gameloft IAB layer (com.gameloft.android.ANMP.GloftM5HM.iab.GMPUtils).
 * The five asynchronous tasks of GMPUtils (GMPUtils$b start, $d product details, $c purchase, $a consume, $e owned purchases)
 * call {@link #run} first (bridge/patch/dex/iap.spec); the answer is built from the data of our server (CRM `iap.prices`), no Google involved.
 * Bundle keys are the ones the Gameloft layer uses: a4 status (0 = ok), a7 purchase JSON, a8 signature, b1 product ids, b3 type.
 * Everything here talks to the layer by reflection, so no obfuscated class has to be known at compile time.
 */
public final class Store {
    private static final String TAG = "mc5store";
    /** Server of the game; the bridge replaces this with the address from its settings. */
    public static volatile String base = "http://127.0.0.1:18080";
    /** Signature of purchases made here: GMP s.v() accepts it without the Google key (patched). */
    public static final String SIGNATURE = "MC5LOCAL";
    private static final LinkedHashMap<String, JSONObject> details = new LinkedHashMap<String, JSONObject>();

    private Store() {}

    /** Called at the start of GMPUtils$x.a(Bundle) in the background thread of the task. */
    public static void run(Object task, Bundle in) {
        String n = task.getClass().getName();
        try {
            if (n.endsWith("GMPUtils$b")) start(task, in);
            else if (n.endsWith("GMPUtils$d")) products(task, in);
            else if (n.endsWith("GMPUtils$c")) purchase(task, in);
            else if (n.endsWith("GMPUtils$a")) Log.i(TAG, "consume: nothing to do (purchases are consumed by the server)");
            else if (n.endsWith("GMPUtils$e")) owned(task, in);
            else Log.w(TAG, "unknown task " + n);
        } catch (Throwable t) {
            Log.e(TAG, "task " + n + " failed", t);
        }
    }

    // ---------------------------------------------------------------- tasks
    private static void start(Object task, Bundle in) throws Exception {
        Object gmp = get(task, "f");                       // GMPUtils
        set(gmp, "a", Boolean.TRUE);                       // "service connected" flag
        in.clear();
        in.putInt("a4", 0);
        Log.i(TAG, "billing service: local");
        finish(task, in);
    }

    private static void products(Object task, Bundle in) throws Exception {
        ArrayList<String> ids = in.getStringArrayList("b1");
        String type = in.getString("b3");
        ArrayList<String> want = new ArrayList<String>();
        if (ids != null) for (String id : ids) if (!details.containsKey(id)) want.add(id);
        Object gmp = get(task, "f");
        if (!want.isEmpty()) {
            StringBuilder q = new StringBuilder();
            for (String id : want) q.append(q.length() == 0 ? "" : ",").append(URLEncoder.encode(id, "UTF-8"));
            JSONArray arr = new JSONArray(http("GET", "/iap/products?ids=" + q + "&type=" + URLEncoder.encode(String.valueOf(type), "UTF-8"), null));
            for (int i = 0; i < arr.length(); i++) {
                JSONObject o = arr.getJSONObject(i);
                details.put(o.getString("productId"), o);
            }
        }
        // like the original: the answer holds every product details object known so far, accumulated under one key
        String key = (String) call(gmp.getClass(), null, "access$500", new Class<?>[] {int.class}, new Object[] {0x21});
        JSONObject root = new JSONObject();
        for (JSONObject o : details.values()) root.accumulate(key, o);
        in.clear();
        in.putString(key, root.toString());
        in.putInt("a4", 0);
        Log.i(TAG, "product details: " + details.size());
        finish(task, in);
    }

    private static void purchase(Object task, Bundle in) throws Exception {
        String product = in.getString("a1");
        String payload = in.getString("a6");
        Object gmp = get(task, "e");                       // GMPUtils (outer instance of $c)
        Object listener = get(task, "d");
        set(gmp, "e", listener);                           // GMPUtils.e: where the purchase result goes (as in the original $c.a)
        JSONObject req = new JSONObject();
        req.put("product_id", product);
        req.put("payload", payload == null ? "" : payload);
        JSONObject order = new JSONObject(http("POST", "/iap/order", req.toString()));
        Bundle out = new Bundle();
        if (order.optInt("status", -1) != 0) {
            out.putInt("a4", -0x3ee);                      // "unknown purchase state" of the original
            Log.w(TAG, "order refused: " + order);
        } else {
            out.putInt("a4", 0);
            out.putString("a7", order.getString("json"));
            out.putString("a8", SIGNATURE);
            Log.i(TAG, "purchase " + product + " order " + order.optString("orderId"));
        }
        if (listener != null) call(listener.getClass(), listener, "a", new Class<?>[] {Bundle.class}, new Object[] {out});
    }

    /**
     * Owned purchases (RESTORE PURCHASES): like the original $e.a / $e$a, the listener gets one Bundle per purchase
     * (a4 = 0, a7 = purchase JSON, a8 = signature, b4 = number from 1, b5 = total); no purchases -> no call at all (as the original).
     * The server lists orders it has not delivered yet (paid or interrupted before the confirmation).
     */
    private static void owned(Object task, Bundle in) throws Exception {
        String type = in.getString("b3");
        if (type == null) return;
        Object listener = get(task, "d");
        JSONArray arr = new JSONArray(http("GET", "/iap/owned?type=" + URLEncoder.encode(type, "UTF-8"), null));
        Log.i(TAG, "owned purchases (" + type + "): " + arr.length());
        for (int i = 0; i < arr.length(); i++) {
            Bundle out = new Bundle();
            out.putInt("a4", 0);
            out.putString("a7", arr.getJSONObject(i).getString("json"));
            out.putString("a8", SIGNATURE);
            out.putInt("b4", i + 1);
            out.putInt("b5", arr.length());
            if (listener != null) call(listener.getClass(), listener, "a", new Class<?>[] {Bundle.class}, new Object[] {out});
        }
    }

    // ---------------------------------------------------------------- helpers
    /** End of a task whose answer is `in`: listener first, then the pending task (as GMPUtils$b/$d do). */
    private static void finish(Object task, Bundle in) throws Exception {
        Object listener = get(task, "d");
        Object pending = get(task, "e");
        if (listener != null) call(listener.getClass(), listener, "a", new Class<?>[] {Bundle.class}, new Object[] {in});
        if (pending != null) {
            Object gmp = get(task, "f");
            Object ctx = get(gmp, "b");
            call(pending.getClass(), pending, "b", new Class<?>[] {android.content.Context.class}, new Object[] {ctx});
        }
    }

    private static String http(String method, String path, String body) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(base + path).openConnection();
        c.setConnectTimeout(8000);
        c.setReadTimeout(15000);
        c.setRequestMethod(method);
        if (body != null) {
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            OutputStream os = c.getOutputStream();
            os.write(body.getBytes("UTF-8"));
            os.close();
        }
        InputStream is = c.getResponseCode() >= 400 ? c.getErrorStream() : c.getInputStream();
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while (is != null && (n = is.read(buf)) > 0) bo.write(buf, 0, n);
        return bo.toString("UTF-8");
    }

    private static Field field(Class<?> k, String name) throws Exception {
        for (Class<?> c = k; c != null; c = c.getSuperclass()) {
            try {
                Field f = c.getDeclaredField(name);
                f.setAccessible(true);
                return f;
            } catch (NoSuchFieldException e) { /* next superclass */ }
        }
        throw new NoSuchFieldException(k.getName() + "." + name);
    }

    private static Object get(Object o, String name) throws Exception { return field(o.getClass(), name).get(o); }

    private static void set(Object o, String name, Object v) throws Exception { field(o.getClass(), name).set(o, v); }

    private static Object call(Class<?> k, Object target, String name, Class<?>[] types, Object[] args) throws Exception {
        for (Class<?> c = k; c != null; c = c.getSuperclass()) {
            try {
                Method m = c.getDeclaredMethod(name, types);
                m.setAccessible(true);
                return m.invoke(target, args);
            } catch (NoSuchMethodException e) { /* next superclass */ }
        }
        throw new NoSuchMethodException(k.getName() + "." + name);
    }
}
