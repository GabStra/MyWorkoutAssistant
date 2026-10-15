package com.gabstra.myworkoutassistant.insights

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Loads the model catalog from an OpenAI-compatible server's `GET /v1/models` endpoint so
 * Settings can offer the server's model ids as a picker instead of requiring manual entry.
 */
object RemoteModelCatalog {
    suspend fun fetchModelIds(
        baseUrl: String,
        apiKey: String,
    ): Result<List<String>> = withContext(Dispatchers.IO) {
        runCatching {
            val client = OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(15, TimeUnit.SECONDS)
                .callTimeout(20, TimeUnit.SECONDS)
                .build()
            val requestBuilder = Request.Builder().url(modelsEndpointUrl(baseUrl)).get()
            val trimmedKey = apiKey.trim()
            // Self-hosted servers commonly run without authentication; sending no header is
            // safer for them than a placeholder bearer (hosted providers need a real key anyway).
            if (trimmedKey.isNotEmpty()) {
                requestBuilder.header("Authorization", "Bearer $trimmedKey")
            }
            client.newCall(requestBuilder.build()).execute().use { response ->
                require(response.isSuccessful) {
                    "The server responded with HTTP ${response.code} while loading the model list."
                }
                val models = try {
                    parseModelIds(response.body?.string().orEmpty())
                } catch (exception: Exception) {
                    throw IllegalArgumentException(
                        "The server response was not a valid model list.",
                        exception,
                    )
                }
                require(models.isNotEmpty()) { "The server returned an empty model list." }
                models
            }
        }
    }

    internal fun modelsEndpointUrl(baseUrl: String): String =
        "${normalizeOpenAiBaseUrl(baseUrl)}/models"

    /** Tolerant of the extra fields OpenAI-compatible servers add to model entries. */
    internal fun parseModelIds(responseBody: String): List<String> {
        val data = JSONObject(responseBody).optJSONArray("data") ?: return emptyList()
        val models = LinkedHashSet<String>()
        for (index in 0 until data.length()) {
            val id = data.optJSONObject(index)?.optString("id").orEmpty().trim()
            if (id.isNotEmpty()) {
                models.add(id)
            }
        }
        return models.sortedWith(String.CASE_INSENSITIVE_ORDER)
    }
}
