package com.gabstra.myworkoutassistant.composables

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.IconButtonDefaults

internal val WearStandardIconButtonSize: Dp = 50.dp
internal val WearStandardIconButtonHitBoxSize: Dp =
    WearStandardIconButtonSize * 1.25f
internal val WearStandardIconButtonIconSize: Dp =
    wearIconSizeForButton(WearStandardIconButtonSize)

// Secondary role (back/reset/confirm): smaller visual, standard minimum touch target.
internal val WearSecondaryIconButtonSize: Dp = 40.dp
internal val WearSecondaryIconButtonHitBoxSize: Dp = 48.dp
internal val WearSecondaryIconButtonIconSize: Dp =
    wearIconSizeForButton(WearSecondaryIconButtonSize)

internal fun wearIconSizeForButton(buttonSize: Dp): Dp =
    IconButtonDefaults.iconSizeFor(buttonSize)
