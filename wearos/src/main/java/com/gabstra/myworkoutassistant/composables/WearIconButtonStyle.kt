package com.gabstra.myworkoutassistant.composables

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.IconButtonDefaults

internal val WearStandardIconButtonSize: Dp = 50.dp
internal val WearStandardIconButtonHitBoxSize: Dp =
    WearStandardIconButtonSize * 1.25f
internal val WearStandardIconButtonIconSize: Dp =
    wearIconSizeForButton(WearStandardIconButtonSize)

internal fun wearIconSizeForButton(buttonSize: Dp): Dp =
    IconButtonDefaults.iconSizeFor(buttonSize)
