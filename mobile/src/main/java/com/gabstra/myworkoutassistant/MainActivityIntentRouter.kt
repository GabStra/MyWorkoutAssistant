package com.gabstra.myworkoutassistant

import android.content.Intent

internal object MainActivityIntentRouter {

    fun route(intent: Intent, appViewModel: AppViewModel) {
        appViewModel.openExternalPage(
            intent.getStringExtra(DataLayerListenerService.PAGE)
        )
    }
}
