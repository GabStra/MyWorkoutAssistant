package com.gabstra.myworkoutassistant.composables

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.takeOrElse
import androidx.compose.ui.graphics.colorspace.ColorSpaces
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ButtonColors
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.FilledTonalButton
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text

/**
 * Wear Material3 button roles (see `androidx.wear.compose.material3`). Prefer these over ad-hoc
 * [Button] / [FilledTonalButton] / [androidx.wear.compose.material3.OutlinedButton] so emphasis stays
 * consistent across screens.
 *
 * - **Primary (filled)** — [WearPrimaryButton] / [WearPrimaryContentButton]: main CTA (Start, Resume,
 *   confirm, list rows that are the primary tap target).
 * - **Secondary (tonal)** — [WearTonalButton] and [ButtonWithText]: lower emphasis than primary
 *   filled (Back, workout list rows when list item is not a strong CTA, optional actions).
 * - **Outlined** — [OutlinedButtonWithText]: use when a border is needed without filling the shape.
 *
 * On small round screens, avoid mixing multiple filled primaries in one glanceable column without
 * hierarchy—use tonal for the supporting action and filled for the one main action.
 */

@Composable
fun WearPrimaryButton(
    modifier: Modifier = Modifier,
    transformation: SurfaceTransformation? = null,
    text: String,
    enabled: Boolean = true,
    onClick: () -> Unit,
    colors: ButtonColors = ButtonDefaults.buttonColors(),
) {
    val (pressedColors, interactionSource) = rememberPressedButtonColors(
        colors = colors,
        fallbackContainerColor = MaterialTheme.colorScheme.primary,
    )
    Button(
        modifier = modifier,
        transformation = transformation,
        enabled = enabled,
        onClick = onClick,
        colors = pressedColors,
        interactionSource = interactionSource,
    ) {
        Text(
            modifier = Modifier.fillMaxWidth(),
            text = text,
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.bodyLarge,
        )
    }
}

@Composable
fun WearPrimaryContentButton(
    modifier: Modifier = Modifier,
    transformation: SurfaceTransformation? = null,
    enabled: Boolean = true,
    onClick: () -> Unit,
    colors: ButtonColors = ButtonDefaults.buttonColors(),
    content: @Composable RowScope.() -> Unit,
) {
    val (pressedColors, interactionSource) = rememberPressedButtonColors(
        colors = colors,
        fallbackContainerColor = MaterialTheme.colorScheme.primary,
    )
    Button(
        modifier = modifier,
        transformation = transformation,
        enabled = enabled,
        onClick = onClick,
        colors = pressedColors,
        interactionSource = interactionSource,
        content = content,
    )
}

@Composable
fun WearTonalButton(
    modifier: Modifier = Modifier,
    transformation: SurfaceTransformation? = null,
    text: String,
    enabled: Boolean = true,
    scaleTextToFit: Boolean = false,
    supportingText: String? = null,
    onClick: () -> Unit,
    colors: ButtonColors = ButtonDefaults.filledTonalButtonColors(),
) {
    val (pressedColors, interactionSource) = rememberPressedButtonColors(
        colors = colors,
        fallbackContainerColor = MaterialTheme.colorScheme.secondaryContainer,
    )
    FilledTonalButton(
        modifier = modifier,
        transformation = transformation,
        enabled = enabled,
        colors = pressedColors,
        interactionSource = interactionSource,
        onClick = onClick,
    ) {
        if (scaleTextToFit) {
            val labelColor = if (enabled) {
                pressedColors.secondaryContentColor
            } else {
                MaterialTheme.colorScheme.onSurface.copy(alpha = 0.38f)
            }
            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                // Wear buttons query intrinsic width; subcomposed text cannot answer that query.
                BasicText(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(20.dp),
                    text = text,
                    style = MaterialTheme.typography.labelMedium.copy(
                        color = labelColor,
                        textAlign = TextAlign.Center,
                        platformStyle = PlatformTextStyle(includeFontPadding = false),
                        lineHeightStyle = LineHeightStyle(
                            alignment = LineHeightStyle.Alignment.Center,
                            trim = LineHeightStyle.Trim.Both,
                        ),
                    ),
                    maxLines = 1,
                    softWrap = false,
                    autoSize = TextAutoSize.StepBased(
                        minFontSize = 8.sp,
                        maxFontSize = MaterialTheme.typography.labelMedium.fontSize,
                    ),
                )
                supportingText?.let {
                    Text(
                        text = it,
                        style = MaterialTheme.typography.labelSmall,
                        color = labelColor,
                        textAlign = TextAlign.Center,
                        maxLines = 1,
                    )
                }
            }
        } else {
            Text(
                modifier = Modifier.fillMaxWidth(),
                text = text,
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Composable
fun WearTonalContentButton(
    modifier: Modifier = Modifier,
    transformation: SurfaceTransformation? = null,
    enabled: Boolean = true,
    onClick: () -> Unit,
    colors: ButtonColors = ButtonDefaults.filledTonalButtonColors(),
    content: @Composable RowScope.() -> Unit,
) {
    val (pressedColors, interactionSource) = rememberPressedButtonColors(
        colors = colors,
        fallbackContainerColor = MaterialTheme.colorScheme.secondaryContainer,
    )
    FilledTonalButton(
        modifier = modifier,
        transformation = transformation,
        enabled = enabled,
        colors = pressedColors,
        interactionSource = interactionSource,
        onClick = onClick,
        content = content,
    )
}

@Composable
internal fun rememberPressedButtonColors(
    colors: ButtonColors,
    fallbackContainerColor: Color,
): Pair<ButtonColors, MutableInteractionSource> {
    val interactionSource = remember { MutableInteractionSource() }
    val isPressed by interactionSource.collectIsPressedAsState()
    val defaultContainerColor = colors.containerColor.takeOrElse { fallbackContainerColor }
    val defaultContentColor = colors.contentColor.takeOrElse { MaterialTheme.colorScheme.onSurface }
    val defaultSecondaryContentColor = colors.secondaryContentColor.takeOrElse { defaultContentColor }
    val defaultIconColor = colors.iconColor.takeOrElse { defaultContentColor }
    val containerColor by animateColorAsState(
        targetValue = if (isPressed) darkenButtonColor(defaultContainerColor) else defaultContainerColor,
        label = "button press",
    )
    val contentColor by animateColorAsState(
        targetValue = if (isPressed) darkenButtonColor(defaultContentColor) else defaultContentColor,
        label = "button content press",
    )
    val secondaryContentColor by animateColorAsState(
        targetValue = if (isPressed) darkenButtonColor(defaultSecondaryContentColor) else defaultSecondaryContentColor,
        label = "button secondary content press",
    )
    val iconColor by animateColorAsState(
        targetValue = if (isPressed) darkenButtonColor(defaultIconColor) else defaultIconColor,
        label = "button icon press",
    )
    return colors.copy(
        containerColor = containerColor,
        contentColor = contentColor,
        secondaryContentColor = secondaryContentColor,
        iconColor = iconColor,
    ) to interactionSource
}

internal fun darkenButtonColor(color: Color): Color {
    val oklab = color.convert(ColorSpaces.Oklab)
    return Color(
        red = oklab.red * 0.8f,
        green = oklab.green,
        blue = oklab.blue,
        alpha = color.alpha,
        colorSpace = ColorSpaces.Oklab,
    ).convert(color.colorSpace)
}
