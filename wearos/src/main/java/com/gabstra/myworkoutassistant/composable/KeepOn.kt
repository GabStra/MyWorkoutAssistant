package com.gabstra.myworkoutassistant.composable

import android.view.WindowManager
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.platform.LocalContext
import com.gabstra.myworkoutassistant.data.findActivity

@Composable
fun KeepOn() {
    val context = LocalContext.current
    val activity = context.findActivity()
    val window = activity?.window

    DisposableEffect(Unit) {
        window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        onDispose {
            window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }
}