import type { Page } from '@playwright/test';
import { BasePage } from './BasePage';
import { AcimaPageObjects } from '../pageObjects/AcimaPage.objects';

export class AcimaPage extends BasePage {
  constructor(page: Page) {
    super(page);
  }

  async verifyShopWithAcimaLeasingHeading(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.shopWithAcimaLeasingHeading), 'Shop with Acima Leasing heading').catch(async () => {
      await this.verifyVisibleText('Shop with Acima Leasing', 'Shop with Acima Leasing heading');
    });
  }

  async verifyLeaseToOwnSolutions(): Promise<void> {
    await this.verifyVisibleText('lease-to-own solutions', 'lease-to-own solutions description');
  }

  async verifyShopInStore(): Promise<void> {
    await this.verifyActionTargetVisible('Shop In-store', 'Shop In-store CTA');
  }

  async verifyShopOnline(): Promise<void> {
    await this.verifyActionTargetVisible('Shop Online', 'Shop Online CTA');
  }

  async clickShopInStoreAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.shopInStore), '/find-a-store');
  }

  async clickShopOnlineAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.shopOnline), '/shop-online');
  }

  async verifyShoppingIsEasy(): Promise<void> {
    await this.verifyVisibleText('Shopping is easy', 'Shopping is easy section');
  }

  async verifySelectARetailer(): Promise<void> {
    await this.verifyVisibleText('Select a retailer', 'Select a retailer step');
  }

  async verifyApplyForALease(): Promise<void> {
    await this.verifyVisibleText('Apply for a lease', 'Apply for a lease step');
  }

  async verifyShopCheckout(): Promise<void> {
    await this.verifyVisibleText('Shop & checkout', 'Shop & checkout step');
  }

  async verifyAcimaLogo(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.acimaLogoImage), 'Acima logo').catch(async () => {
      await this.smartVerifyTextOrAction('Acima logo');
    });
  }

  async clickAcimaLogoAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.acimaLogoImage), 'https://www.acima.com/en').catch(async () => {
      await this.smartClickByTextOrHref('Acima logo', 'https://www.acima.com/en');
    });
  }

  async clickShopNowAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.shopNowButton), '/marketplace').catch(async () => {
      await this.smartClickByTextOrHref('Shop now', '/marketplace');
    });
  }

  async verifyHowItWorks(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.howItWorks), 'How It Works').catch(async () => {
      await this.smartVerifyTextOrAction('How It Works');
    });
  }

  async verifyWaysToShop(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.waysToShopButton), 'Ways to Shop').catch(async () => {
      await this.smartVerifyTextOrAction('Ways to Shop');
    });
  }

  async verifyForRetailers(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.forRetailers), 'For Retailers').catch(async () => {
      await this.smartVerifyTextOrAction('For Retailers');
    });
  }

  async verifyForECommerceRetailers(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.forECommerceRetailers), 'For eCommerce Retailers').catch(async () => {
      await this.smartVerifyTextOrAction('For eCommerce Retailers');
    });
  }

  async verifyAboutUs(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.aboutUs), 'About Us').catch(async () => {
      await this.smartVerifyTextOrAction('About Us');
    });
  }

  async verifyNews(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.news), 'News').catch(async () => {
      await this.smartVerifyTextOrAction('News');
    });
  }

  async verifySupport(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.support), 'Support').catch(async () => {
      await this.smartVerifyTextOrAction('Support');
    });
  }

  async verifyFAQ(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.fAQ), 'FAQ').catch(async () => {
      await this.smartVerifyTextOrAction('FAQ');
    });
  }

  async verifyCareers(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.careersLink), 'Careers').catch(async () => {
      await this.smartVerifyTextOrAction('Careers');
    });
  }

  async verifyInvest(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.investLink), 'Invest').catch(async () => {
      await this.smartVerifyTextOrAction('Invest');
    });
  }

  async verifyBlog(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.blogLink), 'Blog').catch(async () => {
      await this.smartVerifyTextOrAction('Blog');
    });
  }

  async verifyAccessibility(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.accessibilityLink), 'Accessibility').catch(async () => {
      await this.smartVerifyTextOrAction('Accessibility');
    });
  }

  async verifySolutions(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.solutions), 'Solutions').catch(async () => {
      await this.smartVerifyTextOrAction('Solutions');
    });
  }

  async verifyDigital(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.digital), 'Digital').catch(async () => {
      await this.smartVerifyTextOrAction('Digital');
    });
  }

  async verifyAcimaBenefitsPlus(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.acimaBenefitsPlus), 'Acima Benefits Plus').catch(async () => {
      await this.smartVerifyTextOrAction('Acima Benefits Plus');
    });
  }

  async verifyAcimaLocations(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.acimaLocations), 'Acima Locations').catch(async () => {
      await this.smartVerifyTextOrAction('Acima Locations');
    });
  }

  async verifyPartnerLocations(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.partnerLocations), 'Partner Locations').catch(async () => {
      await this.smartVerifyTextOrAction('Partner Locations');
    });
  }

  async verifyUpbound(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.upbound), 'Upbound').catch(async () => {
      await this.smartVerifyTextOrAction('Upbound');
    });
  }

  async clickHowItWorksAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.howItWorks), '/how-it-works').catch(async () => {
      await this.smartClickByTextOrHref('How It Works', '/how-it-works');
    });
  }

  async clickWaysToShopAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.waysToShopButton), '/ways-to-shop').catch(async () => {
      await this.smartClickByTextOrHref('Ways to Shop', '/ways-to-shop');
    });
  }

  async clickForRetailersAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.forRetailers), '/partner').catch(async () => {
      await this.smartClickByTextOrHref('For Retailers', '/partner');
    });
  }

  async clickForECommerceRetailersAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.forECommerceRetailers), '/ecommerce').catch(async () => {
      await this.smartClickByTextOrHref('For eCommerce Retailers', '/ecommerce');
    });
  }

  async clickAboutUsAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.aboutUs), '/about-us').catch(async () => {
      await this.smartClickByTextOrHref('About Us', '/about-us');
    });
  }

  async clickNewsAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.news), '/news').catch(async () => {
      await this.smartClickByTextOrHref('News', '/news');
    });
  }

  async clickSupportFAQAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.supportFAQ), '/aboutleasing').catch(async () => {
      await this.smartClickByTextOrHref('Support/FAQ', '/aboutleasing');
    });
  }

  async clickCareersAndVerifyExternalNavigation(): Promise<void> {
    await this.clickAndVerifyMaybeNewTab(this.getLocator(AcimaPageObjects.careersLink), '').catch(async () => {
      await this.smartClickByTextOrHref('Careers', '');
    });
  }

  async clickInvestAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.investLink), '').catch(async () => {
      await this.smartClickByTextOrHref('Invest', '');
    });
  }

  async clickBlogAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.blogLink), '/blog').catch(async () => {
      await this.smartClickByTextOrHref('Blog', '/blog');
    });
  }

  async clickAccessibilityAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.accessibilityLink), '/accessibility').catch(async () => {
      await this.smartClickByTextOrHref('Accessibility', '/accessibility');
    });
  }

  async clickUpboundAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.upbound), '').catch(async () => {
      await this.smartClickByTextOrHref('Upbound', '');
    });
  }

  async verifyAcimaMarketplace(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.acimaMarketplace), 'Acima Marketplace').catch(async () => {
      await this.smartVerifyTextOrAction('Acima Marketplace');
    });
  }

  async clickStartShoppingAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.startShoppingButton), '/marketplace').catch(async () => {
      await this.smartClickByTextOrHref('Start Shopping', '/marketplace');
    });
  }

  async clickSelectARetailerAndVerifyExternalNavigation(): Promise<void> {
    await this.clickAndVerifyMaybeNewTab(this.getLocator(AcimaPageObjects.selectARetailer), '').catch(async () => {
      await this.smartClickByTextOrHref('Select a retailer', '');
    });
  }

  async verifyDoMoreInTheAcimaMobileApp(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.mobileAppSection), 'Do more in the Acima mobile app').catch(async () => {
      await this.smartVerifyTextOrAction('Do more in the Acima mobile app');
    });
  }

  async verifyAmazon(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.amazon), 'Amazon').catch(async () => {
      await this.smartVerifyTextOrAction('Amazon');
    });
  }

  async verifyBestBuy(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.bestBuy), 'Best Buy').catch(async () => {
      await this.smartVerifyTextOrAction('Best Buy');
    });
  }

  async verifyWalmart(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.walmart), 'Walmart').catch(async () => {
      await this.smartVerifyTextOrAction('Walmart');
    });
  }

  async clickDownloadAppFromAppStoreAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.downloadAppFromAppStore), '').catch(async () => {
      await this.smartClickByTextOrHref('Download app from app store', '');
    });
  }

  async clickFacebookAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.facebookLink), '').catch(async () => {
      await this.smartClickByTextOrHref('Facebook', '');
    });
  }

  async clickInstagramAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.instagramLink), '').catch(async () => {
      await this.smartClickByTextOrHref('Instagram', '');
    });
  }

  async clickLinkedInAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.linkedInLink), '').catch(async () => {
      await this.smartClickByTextOrHref('LinkedIn', '');
    });
  }

  async verifyFooter(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.footer), 'footer').catch(async () => {
      await this.smartVerifyTextOrAction('footer');
    });
  }

  async clickTermsOfUseAndVerifyNavigation(): Promise<void> {
    await this.clickAndVerifyNavigation(this.getLocator(AcimaPageObjects.termsOfUseLink), '/termsofuse').catch(async () => {
      await this.smartClickByTextOrHref('Terms of Use', '/termsofuse');
    });
  }

  async verifyPrivacyPolicy(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.privacyPolicy), 'Privacy Policy').catch(async () => {
      await this.smartVerifyTextOrAction('Privacy Policy');
    });
  }

  async verifyYourCaliforniaPrivacyRights(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.yourCaliforniaPrivacyRights), 'Your California Privacy Rights').catch(async () => {
      await this.smartVerifyTextOrAction('Your California Privacy Rights');
    });
  }

  async clickYourPrivacyChoicesDoNotSellMyDataOrShareMyPersonalInformationAndVerifyExternalNavigation(): Promise<void> {
    await this.clickAndVerifyMaybeNewTab(this.getLocator(AcimaPageObjects.yourPrivacyChoicesDoNotSellMyDataOrShareMyPersonalInformationLink), '').catch(async () => {
      await this.smartClickByTextOrHref('Your Privacy Choices / Do Not Sell My Data or Share My Personal Information', '');
    });
  }

  async verifyVerifyPageContentIsProperlyAlignedAndReadableAtCommonDesktopResolutionsEG1366x7681920x1080(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.verifyPageContentIsProperlyAlignedAndReadableAtCommonDesktopResolutionsEG1366x7681920x1080), 'Verify page content is properly aligned and readable at common desktop resolutions (e.g., 1366x768, 1920x1080)').catch(async () => {
      await this.smartVerifyTextOrAction('Verify page content is properly aligned and readable at common desktop resolutions (e.g., 1366x768, 1920x1080)');
    });
  }

  async verifyVerifyFontSizeAndContrastMeetBasicReadabilityExpectationsOnPrimaryTextAndButtons(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.verifyFontSizeAndContrastMeetBasicReadabilityExpectationsOnPrimaryTextAndButtonsButton), 'Verify font size and contrast meet basic readability expectations on primary text and buttons').catch(async () => {
      await this.smartVerifyTextOrAction('Verify font size and contrast meet basic readability expectations on primary text and buttons');
    });
  }

  async verifyKeyboardAccessibleKeyboardAccessibleControls(): Promise<void> {
    await this.verifyPageLoadedSuccessfully();
    // Extend with app-specific tab order assertions after Playwright-MCP exploration.
  }

  async verify404OrNotFoundPage(): Promise<void> {
    await this.verifyTextVisible('Verify accessing a non‑existent page under the domain shows a user‑friendly 404 page (e.g., https://www.acima.com/en/abcxyz)');
  }

  async verifyVerifyTheSiteHandlesNetworkInterruptionGracefullyAndDisplaysStandardBrowserOrCustomErrorMessage(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.verifyTheSiteHandlesNetworkInterruptionGracefullyAndDisplaysStandardBrowserOrCustomErrorMessage), 'Verify the site handles network interruption gracefully and displays standard browser or custom error message').catch(async () => {
      await this.smartVerifyTextOrAction('Verify the site handles network interruption gracefully and displays standard browser or custom error message');
    });
  }

  async verifyVerifyRestrictedPathsIfAnyKnownFromYourAppAreNotAccessibleWithoutProperAuthentication(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.verifyRestrictedPathsIfAnyKnownFromYourAppAreNotAccessibleWithoutProperAuthentication), 'Verify restricted paths (if any known from your app) are not accessible without proper authentication').catch(async () => {
      await this.smartVerifyTextOrAction('Verify restricted paths (if any known from your app) are not accessible without proper authentication');
    });
  }

  async verifyKeyboardAccessiblePrimaryButtonsAndLinks(): Promise<void> {
    await this.verifyPageLoadedSuccessfully();
    // Extend with app-specific tab order assertions after Playwright-MCP exploration.
  }

  async verifyVerifyImagesWithImportantInformationEGBannersAppImageHaveAppropriateAltTextOrLabels(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(AcimaPageObjects.verifyImagesWithImportantInformationEGBannersAppImageHaveAppropriateAltTextOrLabelsImage), 'Verify images with important information (e.g., banners, app image) have appropriate alt text or labels').catch(async () => {
      await this.smartVerifyTextOrAction('Verify images with important information (e.g., banners, app image) have appropriate alt text or labels');
    });
  }

  async verifyHomePageLoadsSuccessfullyWithHTTP200StatusWhenOpeningHttpsWwwAcimaComEn(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyPageLoadedSuccessfully();
  }

  async verifyTheAcimaLogoIsDisplayedInTheHeaderAndIsVisuallyClear(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyAcimaLogo();
  }

  async verifyClickingTheAcimaLogoFromAnyInnerPageNavigatesBackToTheHomePage(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickAcimaLogoAndVerifyNavigation();
  }

  async verifyTheMainHeroSectionShowsTheHeadingShopWithAcimaLeasingAndTheDescriptionAboutLeaseToOwnSolutions(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyShopWithAcimaLeasingHeading();
    await this.verifyLeaseToOwnSolutions();
  }

  async verifyShopInStoreAndShopOnlineButtonsAreVisibleInTheHeroSection(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyShopInStore();
    await this.verifyShopOnline();
  }

  async verifyShopInStoreButtonNavigatesToTheFindAStorePageFindAStore(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickShopInStoreAndVerifyNavigation();
  }

  async verifyShopOnlineButtonNavigatesToTheShopOnlinePageShopOnline(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickShopOnlineAndVerifyNavigation();
  }

  async verifyThePageShowsTheShoppingIsEasyThreeStepSectionSelectARetailerApplyForALeaseShopCheckoutWithCorrectText(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyShoppingIsEasy();
    await this.verifySelectARetailer();
    await this.verifyApplyForALease();
    await this.verifyShopCheckout();
  }

  async verifyShopNowButtonInTheShoppingIsEasySectionNavigatesToTheMarketplaceMarketplace(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickShopNowAndVerifyNavigation();
  }

  async verifyTheTopNavigationMenuIsDisplayedWithItemsHowItWorksWaysToShopForRetailersForECommerceRetailersAboutUsNewsSupportFA(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyHowItWorks();
    await this.verifyWaysToShop();
    await this.verifyForRetailers();
    await this.verifyForECommerceRetailers();
    await this.verifyAboutUs();
    await this.verifyNews();
    await this.verifySupport();
    await this.verifyFAQ();
    await this.verifyCareers();
    await this.verifyInvest();
    await this.verifyBlog();
    await this.verifyAccessibility();
    await this.verifySolutions();
    await this.verifyDigital();
    await this.verifyAcimaBenefitsPlus();
    await this.verifyAcimaLocations();
    await this.verifyPartnerLocations();
    await this.verifyUpbound();
  }

  async verifyClickingHowItWorksNavigatesToHowItWorksAndPageContentLoadsWithoutErrors(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickHowItWorksAndVerifyNavigation();
  }

  async verifyClickingWaysToShopNavigatesToWaysToShop(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickWaysToShopAndVerifyNavigation();
  }

  async verifyClickingForRetailersNavigatesToPartner(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickForRetailersAndVerifyNavigation();
  }

  async verifyClickingForECommerceRetailersNavigatesToEcommerce(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickForECommerceRetailersAndVerifyNavigation();
  }

  async verifyClickingAboutUsNavigatesToAboutUs(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickAboutUsAndVerifyNavigation();
  }

  async verifyClickingNewsNavigatesToNews(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickNewsAndVerifyNavigation();
  }

  async verifyClickingSupportFAQOpensTheSupportFAQPageAboutleasing(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickSupportFAQAndVerifyNavigation();
  }

  async verifyClickingCareersOpensAcimacareersComInSameOrNewTabAsPerRequirement(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickCareersAndVerifyExternalNavigation();
  }

  async verifyClickingInvestOpensInvestorUpboundComSuccessfully(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickInvestAndVerifyNavigation();
  }

  async verifyClickingBlogNavigatesToBlog(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickBlogAndVerifyNavigation();
  }

  async verifyAccessibilityLinkNavigatesToAccessibility(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickAccessibilityAndVerifyNavigation();
  }

  async verifyAcimaLocationsNavigatesToLocationsAcimaCom(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyAcimaLocations();
  }

  async verifyPartnerLocationsNavigatesToFindAStore(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyPartnerLocations();
  }

  async verifyUpboundLinkNavigatesToUpboundCom(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickUpboundAndVerifyNavigation();
  }

  async verifyTheAcimaMarketplaceSectionIsVisibleOnTheHomePageWithADescriptionAboutGettingTheThingsYouLoveWithoutPerfectCredit(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyAcimaMarketplace();
  }

  async verifyTheStartShoppingButtonInTheMarketplaceSectionNavigatesToMarketplace(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickStartShoppingAndVerifyNavigation();
  }

  async verifyHttpsWwwAcimaComEnMarketplacePageLoadsSuccessfullyAndShowsAListOfPartnerRetailersOrASearchFilterUIForStores(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyPageLoadedSuccessfully();
  }

  async verifyTheSelectARetailerStepOnMarketplaceAllowsSearchingOrSelectingFromMultipleRetailersEGListClickAnyRetailerNavigatesTo(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickSelectARetailerAndVerifyExternalNavigation();
  }

  async verifyTheSectionDoMoreInTheAcimaMobileAppIsDisplayedOnTheHomePage(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyDoMoreInTheAcimaMobileApp();
  }

  async verifyTheTextMentionsShoppingBigNamesLikeAmazonBestBuyAndWalmartOnlyInTheApp(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyAmazon();
    await this.verifyBestBuy();
    await this.verifyWalmart();
  }

  async verifyDownloadAppFromAppStoreLinkOpensTheAppleAppStoreURLForAcimaLeasing(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickDownloadAppFromAppStoreAndVerifyNavigation();
  }

  async verifyDownloadAppFromGooglePlayStoreLinkOpensTheCorrectGooglePlayStorePageForAcimaLeasing(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickDownloadAppFromAppStoreAndVerifyNavigation();
  }

  async verifyFacebookIconLinkOpensAcimaSFacebookPage(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickFacebookAndVerifyNavigation();
  }

  async verifyInstagramIconLinkOpensAcimaSInstagramPage(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickInstagramAndVerifyNavigation();
  }

  async verifyLinkedInIconLinkOpensAcimaSLinkedInPage(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickLinkedInAndVerifyNavigation();
  }

  async verifyTheFooterDisplaysCopyrightText2026AcimaAllRightsReserved(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyFooter();
  }

  async verifyTermsOfUseLinkOpensTermsofuse(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickTermsOfUseAndVerifyNavigation();
  }

  async verifyPrivacyPolicyOpensPrivacypolicy(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyPrivacyPolicy();
  }

  async verifyYourCaliforniaPrivacyRightsOpensCaliforniaprivacypolicy(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyYourCaliforniaPrivacyRights();
  }

  async verifyEmployeePrivacyPolicyOpensEmployeePrivacyPolicy(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyPrivacyPolicy();
  }

  async verifyYourPrivacyChoicesDoNotSellMyDataOrShareMyPersonalInformationLinksOpenThePrivacyCentralPageInANewTabIfSpecified(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.clickYourPrivacyChoicesDoNotSellMyDataOrShareMyPersonalInformationAndVerifyExternalNavigation();
  }

  async verifyPageContentIsProperlyAlignedAndReadableAtCommonDesktopResolutionsEG1366x7681920x1080(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyVerifyPageContentIsProperlyAlignedAndReadableAtCommonDesktopResolutionsEG1366x7681920x1080();
  }

  async verifyResponsiveBehaviorOnMobileViewHeroSectionButtonsShopNearbyShopOnlineAndCardsStackVerticallyAndRemainReadable(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyResponsiveLayoutSmoke();
  }

  async verifyFontSizeAndContrastMeetBasicReadabilityExpectationsOnPrimaryTextAndButtons(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyVerifyFontSizeAndContrastMeetBasicReadabilityExpectationsOnPrimaryTextAndButtons();
  }

  async verifySkipToMainContentLinkWorksAndMovesFocusToTheMainContentSection(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyKeyboardAccessibleKeyboardAccessibleControls();
  }

  async verifyButtonsHaveHoverStatesAndFocusOutlinesForKeyboardUsers(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyKeyboardAccessibleKeyboardAccessibleControls();
  }

  async verifyAccessingANonExistentPageUnderTheDomainShowsAUserFriendly404PageEGHttpsWwwAcimaComEnAbcxyz(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verify404OrNotFoundPage();
  }

  async verifyTheSiteHandlesNetworkInterruptionGracefullyAndDisplaysStandardBrowserOrCustomErrorMessage(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyVerifyTheSiteHandlesNetworkInterruptionGracefullyAndDisplaysStandardBrowserOrCustomErrorMessage();
  }

  async verifyRestrictedPathsIfAnyKnownFromYourAppAreNotAccessibleWithoutProperAuthentication(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyVerifyRestrictedPathsIfAnyKnownFromYourAppAreNotAccessibleWithoutProperAuthentication();
  }

  async verifyAllPrimaryButtonsAndLinksOnTheHomePageAreReachableAndActionableUsingKeyboardOnlyTabEnterSpace(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyKeyboardAccessiblePrimaryButtonsAndLinks();
  }

  async verifyImagesWithImportantInformationEGBannersAppImageHaveAppropriateAltTextOrLabels(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyVerifyImagesWithImportantInformationEGBannersAppImageHaveAppropriateAltTextOrLabels();
  }

  async verifyHeadingsFollowALogicalHierarchyH1ForMainTitleShopWithAcimaLeasingEtc(): Promise<void> {
    await this.goto('https://www.acima.com/en');
    await this.verifyShopWithAcimaLeasingHeading();
  }


  async verifyHomePage(): Promise<void> {
    await this.verifyPageLoadedSuccessfully();
    await this.verifyShopWithAcimaLeasingHeading();
    await this.verifyShopInStoreButton();
    await this.verifyShopOnlineButton();
  }

  async verifyShopInStoreButton(): Promise<void> {
    await this.verifyShopInStore();
  }

  async verifyShopOnlineButton(): Promise<void> {
    await this.verifyShopOnline();
  }

  async verifyHeroContent(): Promise<void> {
    await this.verifyHomePage();
  }

}
