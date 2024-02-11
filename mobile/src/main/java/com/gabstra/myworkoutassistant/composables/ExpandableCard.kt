package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.ArrowDropUp
import androidx.compose.material3.Card
import androidx.compose.material3.CardColors
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.unit.dp

@Composable
fun ExpandableCard(
    modifier : Modifier = Modifier,
    isExpandable:Boolean = true,
    isOpen: Boolean = false,
    title: @Composable (modifier: Modifier) -> Unit,
    content: @Composable () -> Unit,
    onOpen: () -> Unit,
    onClose: () -> Unit,
    colors: CardColors = CardDefaults.cardColors()
){
    var openStatus by remember {
        mutableStateOf(isOpen)
    }

    Card(
        modifier = modifier,
        colors = colors
    ){
        Column(
            modifier = Modifier.fillMaxWidth(),

        ){
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth(),
            ){
                title(Modifier.weight(1f))
                IconButton(
                    modifier = Modifier.alpha(if(isExpandable) 1f else 0.4f),
                    onClick = { if(isExpandable){
                        openStatus = !openStatus
                        if(openStatus){
                            onOpen()
                        }else{
                            onClose()
                        }
                    } }) {
                    Icon(imageVector = if(openStatus) Icons.Filled.ArrowDropDown else Icons.Filled.ArrowDropUp, contentDescription = "Back")
                }
            }
            if(openStatus){
                content()
            }
        }
    }
}