package com.gabstra.myworkoutassistant

import android.content.Intent

internal object MainActivityIntentRouter {

    fun route(intent: Intent, appViewModel: AppViewModel) {
        when (intent.getStringExtra(DataLayerListenerService.PAGE)) {
            "workouts" -> appViewModel.setScreenData(ScreenData.Workouts(1))
            "settings" -> appViewModel.setScreenData(ScreenData.Settings())
        }
    }
}
