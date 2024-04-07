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
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("kotlin-kapt")
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
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
    }
    composeOptions {
        kotlinCompilerExtensionVersion = "1.4.3"
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    implementation(project(":shared"))
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("com.google.android.gms:play-services-wearable:18.1.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.6.2")
    implementation("androidx.activity:activity-compose:1.7.2")
    implementation(platform("androidx.compose:compose-bom:2023.03.00"))

    val lifecycle_version = "2.6.2"

    // ViewModel
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:$lifecycle_version")
    // ViewModel utilities for Compose
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:$lifecycle_version")

    // Lifecycles only (without ViewModel or LiveData)
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:$lifecycle_version")
    // Lifecycle utilities for Compose
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.6.2")
    implementation("androidx.navigation:navigation-compose:2.7.7")


    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("com.google.accompanist:accompanist-permissions:0.35.0-alpha")
    implementation("com.google.code.gson:gson:2.9.0")
    implementation("androidx.compose.material:material-icons-extended:1.6.1")
    implementation("com.google.accompanist:accompanist-permissions:0.35.0-alpha")
    implementation("com.google.android.horologist:horologist-datalayer:0.5.21")
    implementation("com.google.android.horologist:horologist-datalayer-phone:0.5.21")
    kapt("androidx.room:room-compiler:+")
    implementation("androidx.room:room-ktx:+")


    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
    androidTestImplementation(platform("androidx.compose:compose-bom:2023.03.00"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")

    implementation("com.patrykandpatrick.vico:compose:2.0.0-alpha.10")
    implementation("com.kizitonwose.calendar:compose:2.5.0")
}