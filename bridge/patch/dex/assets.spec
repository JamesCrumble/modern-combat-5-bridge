# Asset packs are local files: Google Play Core is not used (documentation/protocol.md).
# onPluginStart does not create the AssetPackManager (field c stays null), pause/resume do not (un)register its listener, openWifiConfirmation is a no-op.
# Variable PKG_FILES = /data/user/0/<package>/files/assetpacks/
@class com/gameloft/android/ANMP/GloftM5HM/installer/AssetsManagerPlugin
@method getAbsoluteAssetPath(I)Ljava/lang/String;
.locals 3
const/4 v0, 0x0
if-ltz p0, :ret
sget-object v1, Lcom/gameloft/android/ANMP/GloftM5HM/installer/AssetsManagerPlugin;->f:Ljava/util/Vector;
invoke-virtual {v1}, Ljava/util/Vector;->size()I
move-result v1
if-ge p0, v1, :ret
sget-object v1, Lcom/gameloft/android/ANMP/GloftM5HM/installer/AssetsManagerPlugin;->f:Ljava/util/Vector;
invoke-virtual {v1, p0}, Ljava/util/Vector;->get(I)Ljava/lang/Object;
move-result-object v1
check-cast v1, Ljava/lang/String;
new-instance v0, Ljava/lang/StringBuilder;
invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
const-string v2, "${PKG_FILES}"
invoke-virtual {v0, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
const-string v2, "/601213/601213/assets"
invoke-virtual {v0, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
move-result-object v0
:ret
return-object v0
@end

@class com/gameloft/android/ANMP/GloftM5HM/installer/AssetsManagerPlugin
@method isDownloadCompleted()Z
.locals 2
sget-boolean v0, Lcom/gameloft/android/ANMP/GloftM5HM/installer/AssetsManagerPlugin;->j:Z
if-nez v0, :done
const/4 v0, 0x1
sput-boolean v0, Lcom/gameloft/android/ANMP/GloftM5HM/installer/AssetsManagerPlugin;->j:Z
invoke-static {}, Lcom/gameloft/android/ANMP/GloftM5HM/PackageUtils/JNIBridge;->AssetPacksRefresh()V
:done
const/4 v0, 0x1
return v0
@end

@class com/gameloft/android/ANMP/GloftM5HM/installer/AssetsManagerPlugin
@method onPluginStart(Landroid/app/Activity;Landroid/view/ViewGroup;)V
.locals 0
sput-object p1, Lcom/gameloft/android/ANMP/GloftM5HM/installer/AssetsManagerPlugin;->b:Landroid/app/Activity;
return-void
@end

@class com/gameloft/android/ANMP/GloftM5HM/installer/AssetsManagerPlugin
@method onPreNativePause()V
.locals 1
const/4 v0, 0x0
sput-boolean v0, Lcom/gameloft/android/ANMP/GloftM5HM/installer/AssetsManagerPlugin;->k:Z
return-void
@end

@class com/gameloft/android/ANMP/GloftM5HM/installer/AssetsManagerPlugin
@method onPreNativeResume()V
.locals 1
const/4 v0, 0x1
sput-boolean v0, Lcom/gameloft/android/ANMP/GloftM5HM/installer/AssetsManagerPlugin;->k:Z
return-void
@end

@class com/gameloft/android/ANMP/GloftM5HM/installer/AssetsManagerPlugin
@method openWifiConfirmation()V
.locals 0
return-void
@end
