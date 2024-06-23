import java.util.Properties

val versionPropsFile = file("version.properties.mobile")
val versionProps = Properties()

if (versionPropsFile.canRead()) {
    versionProps.load(versionPropsFile.inputStream())
}

if (versionProps.isEmpty) {
    println("versionProps is empty. No properties were loaded.")
} else {
    versionProps.forEach { key, value ->
        println("$key: $value")
    }
}

// Keep the oldVersionCode unchanged
val oldVersionCode = versionProps["VERSION_CODE"].toString().toInt()

val oldVersionName = versionProps["VERSION_NAME"].toString()
val versionComponents = oldVersionName.split(".")
val majorVersion = versionComponents[0].toInt()
val minorVersion = versionComponents[1].toInt()
// Increment the patch version, or set to 1 if it's not explicitly set
val patchVersion = if (versionComponents.size > 2) versionComponents[2].toInt() + 1 else 1

// Construct the new version name with the incremented patch version
val newVersionName = "$majorVersion.$minorVersion.$patchVersion"

println("NEW VERSION_CODE $newVersionName")

// Update the properties file with the new version name
// Note: We are not updating the VERSION_CODE here, only the VERSION_NAME
versionProps["VERSION_NAME"] = newVersionName
versionProps.store(versionPropsFile.writer(), null)

plugins {
    id("org.jetbrains.kotlin.plugin.compose") version "2.0.0"
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.devtools.ksp")
}

composeCompiler {
    enableStrongSkippingMode = true
}

android {
    namespace = "com.gabstra.myworkoutassistant"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.gabstra.myworkoutassistant"
        minSdk = 30
        targetSdk = 33
        versionCode = oldVersionCode
        versionName = newVersionName
        vectorDrawables {
            useSupportLibrary = true
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    implementation(project(":shared"))
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("com.google.android.gms:play-services-wearable:18.2.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.2")
    implementation("androidx.activity:activity-compose:1.9.0")
    implementation(platform("androidx.compose:compose-bom:2024.06.00"))
    implementation("com.github.nanihadesuka:LazyColumnScrollbar:2.1.0")

    val lifecycle_version = "2.8.2"

    // ViewModel
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:$lifecycle_version")
    // ViewModel utilities for Compose
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:$lifecycle_version")

    // Lifecycles only (without ViewModel or LiveData)
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:$lifecycle_version")
    // Lifecycle utilities for Compose
    implementation("androidx.lifecycle:lifecycle-runtime-compose:$lifecycle_version")
    implementation("androidx.navigation:navigation-compose:2.7.7")


    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("com.google.accompanist:accompanist-permissions:0.35.0-alpha")
    implementation("com.google.code.gson:gson:2.10.1")
    implementation("androidx.compose.material:material-icons-extended:1.6.8")
    implementation("com.google.accompanist:accompanist-permissions:0.35.0-alpha")
    implementation("com.google.android.horologist:horologist-datalayer:0.5.21")
    implementation("com.google.android.horologist:horologist-datalayer-phone:0.5.21")
    ksp("androidx.room:room-compiler:+")
    implementation("androidx.room:room-ktx:+")


    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
    androidTestImplementation(platform("androidx.compose:compose-bom:2024.06.00"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")

    implementation("com.patrykandpatrick.vico:compose:2.0.0-alpha.21")
    implementation("com.kizitonwose.calendar:compose:2.5.0")
}




