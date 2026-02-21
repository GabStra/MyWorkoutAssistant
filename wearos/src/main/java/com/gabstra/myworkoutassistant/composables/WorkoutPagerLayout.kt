package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.dp

object WorkoutPagerLayoutTokens {
    val WorkoutHeaderTopPadding = 10.dp
    val WorkoutHeaderHeight = 25.dp
    val HorizontalPagerBottomContentPadding = 20.dp
    val ExerciseTitleHorizontalPadding = 22.5.dp
    val OverlayContentHorizontalPadding = 14.dp
    val HeartRateZoneVisualScale = 1f
    val ExerciseIndicatorVisualScale = 1f
    val HeartRateReadoutAnchorOffsetX = 0.dp
}

val WorkoutPagerHeaderReservedHeight =
    WorkoutPagerLayoutTokens.WorkoutHeaderTopPadding + WorkoutPagerLayoutTokens.WorkoutHeaderHeight

val WorkoutPagerPageSafeAreaPadding = PaddingValues(
    top = WorkoutPagerHeaderReservedHeight,
    bottom = WorkoutPagerLayoutTokens.HorizontalPagerBottomContentPadding
)

fun Modifier.overlayVisualScale(scale: Float): Modifier =
    graphicsLayer {
        scaleX = scale
        scaleY = scale
    }
