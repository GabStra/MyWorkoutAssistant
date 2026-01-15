# Add project specific ProGuard rules here.
# You can control the set of applied configuration files using the
# proguardFiles setting in build.gradle.
#
# For more details, see
#   http://developer.android.com/guide/developing/tools/proguard.html

# If your project uses WebView with JS, uncomment the following
# and specify the fully qualified class name to the JavaScript interface
# class:
#-keepclassmembers class fqcn.of.javascript.interface.for.webview {
#   public *;
#}

# Uncomment this to preserve the line number information for
# debugging stack traces.
#-keepattributes SourceFile,LineNumberTable

# If you keep the line number information, uncomment this to
# hide the original source file name.
#-renamesourcefileattribute SourceFile

# Keep annotations needed by Room and Gson.
-keepattributes Signature,RuntimeVisibleAnnotations,RuntimeVisibleParameterAnnotations,AnnotationDefault

# Room (database/DAO/entity annotations + generated references).
-keep class * extends androidx.room.RoomDatabase { *; }
-keep @androidx.room.Database class * { *; }
-keep @androidx.room.Entity class * { *; }
-keep @androidx.room.Dao class * { *; }
-keepclassmembers class * {
    @androidx.room.* <fields>;
}

# Gson (reflection + TypeToken).
-keep class com.google.gson.reflect.TypeToken { *; }
-keep class * extends com.google.gson.reflect.TypeToken
-keep class * implements com.google.gson.JsonSerializer { *; }
-keep class * implements com.google.gson.JsonDeserializer { *; }
-keepclassmembers class * {
    @com.google.gson.annotations.SerializedName <fields>;
}

# Preserve JSON field names for shared models stored on disk/synced between devices.
-keepclassmembers class com.gabstra.myworkoutassistant.shared.** { <fields>; }

# Keep shared JSON models and adapters stable across phone/watch builds.
-keep class com.gabstra.myworkoutassistant.shared.adapters.** { *; }
-keep class com.gabstra.myworkoutassistant.shared.workoutcomponents.** { *; }
-keep class com.gabstra.myworkoutassistant.shared.sets.** { *; }
-keep class com.gabstra.myworkoutassistant.shared.setdata.** { *; }
-keep class com.gabstra.myworkoutassistant.shared.equipments.** { *; }
-keep class com.gabstra.myworkoutassistant.shared.AppBackup { *; }
-keep class com.gabstra.myworkoutassistant.shared.WorkoutStore { *; }
-keep class com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore { *; }
-keep class com.gabstra.myworkoutassistant.shared.Workout { *; }
-keep class com.gabstra.myworkoutassistant.shared.WorkoutPlan { *; }
-keep class com.gabstra.myworkoutassistant.shared.WorkoutSchedule { *; }
-keep class com.gabstra.myworkoutassistant.shared.WorkoutRecord { *; }
-keep class com.gabstra.myworkoutassistant.shared.WorkoutHistory { *; }
-keep class com.gabstra.myworkoutassistant.shared.SetHistory { *; }
-keep class com.gabstra.myworkoutassistant.shared.ExerciseInfo { *; }
-keep class com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression { *; }
-keep class com.gabstra.myworkoutassistant.shared.ErrorLog { *; }
-keepclassmembers enum com.gabstra.myworkoutassistant.shared.** { *; }
