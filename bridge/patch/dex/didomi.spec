# Consent SDK Didomi without network (documentation/client-patches.md): the SDK needs sdk.privacy-center.org (config, vendor list, web notice);
# offline a new player waited forever on the first mission load (~88 %): the SDK wanted to show its web notice. The wrapper the native part
# talks to (com/gameloft/didomiwrapper/DidomiWrapper) no longer starts the SDK: StartDidomi reports "ready" at once (NativeOnReady, as the
# SDK's onReady callback did), consent never has to be collected, no notice is ever shown. The other getters already catch the exception
# of an SDK that was not initialized and return their defaults.
@newclass mc5/DidomiReady
.class public final Lmc5/DidomiReady;
.super Ljava/lang/Object;
.implements Ljava/lang/Runnable;

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public run()V
    .locals 0
    invoke-static {}, Lcom/gameloft/didomiwrapper/DidomiWrapper;->b()V
    return-void
.end method
@end

@class com/gameloft/didomiwrapper/DidomiWrapper
@method StartDidomi(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V
    .locals 1
    new-instance v0, Lmc5/DidomiReady;
    invoke-direct {v0}, Lmc5/DidomiReady;-><init>()V
    invoke-static {v0}, Lcom/gameloft/didomiwrapper/Utils;->PostOnMainThread(Ljava/lang/Runnable;)V
    return-void
@end

@class com/gameloft/didomiwrapper/DidomiWrapper
@method IsReady()Z
    .locals 1
    const/4 v0, 0x1
    return v0
@end

@class com/gameloft/didomiwrapper/DidomiWrapper
@method ShouldConsentBeCollected()Z
    .locals 1
    const/4 v0, 0x0
    return v0
@end

@class com/gameloft/didomiwrapper/DidomiWrapper
@method IsNoticeVisible()Z
    .locals 1
    const/4 v0, 0x0
    return v0
@end

@class com/gameloft/didomiwrapper/DidomiWrapper
@method IsPreferencesVisible()Z
    .locals 1
    const/4 v0, 0x0
    return v0
@end

@class com/gameloft/didomiwrapper/DidomiWrapper
@method SetupUI()V
    .locals 0
    return-void
@end

@class com/gameloft/didomiwrapper/DidomiWrapper
@method ShowNotice()V
    .locals 0
    return-void
@end

@class com/gameloft/didomiwrapper/DidomiWrapper
@method ShowPreferences()V
    .locals 0
    return-void
@end

@class com/gameloft/didomiwrapper/DidomiWrapper
@method ShowVendors()V
    .locals 0
    return-void
@end

@class com/gameloft/didomiwrapper/DidomiWrapper
@method HideNotice()V
    .locals 0
    return-void
@end

@class com/gameloft/didomiwrapper/DidomiWrapper
@method HidePreferences()V
    .locals 0
    return-void
@end
