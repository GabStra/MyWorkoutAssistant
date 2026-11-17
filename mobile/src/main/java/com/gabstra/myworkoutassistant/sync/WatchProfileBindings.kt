package com.gabstra.myworkoutassistant.sync

import android.content.Context
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken

/**
 * Which profile each paired watch follows.
 *
 * The watch owns the choice and reports it; the phone keeps it so it can send that watch the
 * right data and show the binding.
 */
object WatchProfileBindings {
    private const val PREFS = "watch_profile_bindings"
    private const val KEY = "bindings"

    private val gson = Gson()
    private val mapType = object : TypeToken<Map<String, String>>() {}.type

    fun all(context: Context): Map<String, String> {
        val raw = prefs(context).getString(KEY, null) ?: return emptyMap()
        return runCatching { gson.fromJson<Map<String, String>>(raw, mapType) }
            .getOrNull()
            .orEmpty()
    }

    fun bind(context: Context, nodeId: String, profileId: String) {
        val updated = all(context) + (nodeId to profileId)
        prefs(context).edit().putString(KEY, gson.toJson(updated)).apply()
    }

    fun boundProfileIds(context: Context): Set<String> = all(context).values.toSet()

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
