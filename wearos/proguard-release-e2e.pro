# Release instrumentation and the target app share these runtime libraries.
# R8 cannot see calls originating in the separately compiled test APK, so keep
# the shared test runtime only for release builds assembled by the E2E runner.
-keep class androidx.tracing.** { *; }
-keep class kotlin.** { *; }
-keep class kotlinx.coroutines.** { *; }
-keep class com.gabstra.myworkoutassistant.e2e.** { *; }
-keep class com.gabstra.myworkoutassistant.shared.** { *; }
